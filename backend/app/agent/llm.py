"""Client LLM cho moi endpoint OpenAI-compatible (OpenAI, Groq, Gemini, OpenRouter, DeepSeek, Ollama, ...).

Chuan hoa ve chuoi su kien don gian de orchestrator khong phu thuoc provider:
    ("provider", label, is_fallback) | ("text", str)
    | ("tool_call", index, id|None, name|None, args_fragment, extra_content|None) | ("finish", reason)
    | ("usage", prompt_tokens, completion_tokens)   (neu provider tra ve)

Failover: thu LLM chinh, neu loi (429, 5xx, mat ket noi, loi kiem tra tool...) TRUOC KHI tra ra noi dung nao
thi chuyen sang LLM phu. Da stream ra chu roi ma loi thi KHONG doi model giua chung (tranh cau tra loi lai).
LLM bi loi 429 duoc "nghi" (cooldown) de cac luot sau khong mat thoi gian thu lai.
"""
from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from app.config import settings

log = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    pass


class LLM(Protocol):
    def stream_chat(self, messages: list[dict], tools: list[dict]) -> Iterator[tuple]: ...


def _is_local(url: str) -> bool:
    return "localhost" in url or "127.0.0.1" in url or "ollama" in url or "host.docker.internal" in url


def supports_nullable_types(base_url: str) -> bool:
    """Gemini chi ho tro mot phan JSON Schema (khong nhan type dang mang ["string","null"])."""
    return "googleapis.com" not in base_url


def is_google(base_url: str) -> bool:
    return "googleapis.com" in base_url


# Gemini 3 bat buoc gui lai `thought_signature` cua moi function call. Tool call do model KHAC tao ra
# (vd Groq truoc khi failover) khong co chu ky -> dung gia tri Google cho phep khi chuyen lich su.
DUMMY_THOUGHT_SIGNATURE = "skip_thought_signature_validator"


def adapt_messages(messages: list[dict], base_url: str) -> list[dict]:
    """Moi provider mot kieu: Gemini can extra_content (thought_signature), provider khac co the tu choi truong la."""
    out = []
    google = is_google(base_url)
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            m = {**m, "tool_calls": [dict(tc) for tc in m["tool_calls"]]}
            for tc in m["tool_calls"]:
                if google:
                    sig = ((tc.get("extra_content") or {}).get("google") or {}).get("thought_signature")
                    tc["extra_content"] = {"google": {"thought_signature": sig or DUMMY_THOUGHT_SIGNATURE}}
                else:
                    tc.pop("extra_content", None)
        out.append(m)
    return out


def strip_nullable(tools: list[dict]) -> list[dict]:
    out = copy.deepcopy(tools)
    for t in out:
        for v in t["function"]["parameters"].get("properties", {}).values():
            if isinstance(v.get("type"), list):
                v["type"] = next(x for x in v["type"] if x != "null")
    return out


# ---- cooldown dung chung giua cac request (process-wide) ----
_cool_until: dict[str, float] = {}
_lock = threading.Lock()


def _cooldown(label: str, seconds: float) -> None:
    with _lock:
        _cool_until[label] = time.monotonic() + seconds


def _cooling(label: str) -> float:
    with _lock:
        return max(0.0, _cool_until.get(label, 0.0) - time.monotonic())


@dataclass
class Provider:
    label: str
    base_url: str
    api_key: str
    model: str
    is_fallback: bool
    max_retries: int

    def __post_init__(self):
        from openai import OpenAI

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key or "not-needed", timeout=120,
                             max_retries=self.max_retries)

    def stream(self, messages: list[dict], tools: list[dict]) -> Iterator[tuple]:
        if tools and not supports_nullable_types(self.base_url):
            tools = strip_nullable(tools)
        messages = adapt_messages(messages, self.base_url)
        kwargs = dict(model=self.model, messages=messages, temperature=settings.llm_temperature)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if not settings.llm_stream:
            r = self.client.chat.completions.create(**kwargs)
            ch = r.choices[0]
            if ch.message.content:
                yield ("text", ch.message.content)
            for i, tc in enumerate(ch.message.tool_calls or []):
                yield ("tool_call", i, tc.id, tc.function.name, tc.function.arguments or "", _extra(tc))
            if r.usage:
                yield ("usage", r.usage.prompt_tokens or 0, r.usage.completion_tokens or 0)
            yield ("finish", ch.finish_reason)
            return
        if settings.llm_stream_usage:
            kwargs["stream_options"] = {"include_usage": True}  # chunk cuoi mang usage (choices rong)
        stream = self.client.chat.completions.create(stream=True, **kwargs)
        finish = None
        # Mot so provider (vd Gemini) khong gui `index` cho tool call -> tu danh so theo id
        id_to_idx: dict[str, int] = {}
        last_idx = -1
        for chunk in stream:
            u = getattr(chunk, "usage", None)
            if u:
                yield ("usage", u.prompt_tokens or 0, u.completion_tokens or 0)
            if not chunk.choices:
                continue
            ch = chunk.choices[0]
            delta = ch.delta
            if delta and delta.content:
                yield ("text", delta.content)
            for tc in (delta.tool_calls or []) if delta else []:
                if tc.index is not None:
                    idx = tc.index
                elif tc.id and tc.id not in id_to_idx:
                    idx = last_idx + 1
                elif tc.id:
                    idx = id_to_idx[tc.id]
                else:
                    idx = max(last_idx, 0)
                if tc.id:
                    id_to_idx[tc.id] = idx
                last_idx = max(last_idx, idx)
                fn = tc.function
                yield ("tool_call", idx, tc.id, fn.name if fn else None, (fn.arguments or "") if fn else "",
                       _extra(tc))
            if ch.finish_reason:
                finish = ch.finish_reason
        yield ("finish", finish)


def _extra(tc) -> dict | None:
    """Truong rieng cua provider tren tool call (vd Gemini: extra_content.google.thought_signature)."""
    extra = getattr(tc, "model_extra", None) or {}
    return extra.get("extra_content") or getattr(tc, "extra_content", None)


def _cooldown_for(err: Exception) -> float:
    msg = str(err)
    if type(err).__name__ == "RateLimitError":
        if "per day" in msg or "(TPD)" in msg or "(RPD)" in msg or "quota" in msg.lower():
            return settings.llm_cooldown_daily_limit_seconds
        return settings.llm_cooldown_seconds
    return 30.0  # 5xx / mat ket noi / loi khac: nghi ngan


class FailoverLLM:
    def __init__(self, providers: list[Provider]):
        if not providers:
            raise LLMNotConfigured("Chưa cấu hình LLM_API_KEY trong .env")
        self.providers = providers

    @property
    def label(self) -> str:
        return " → ".join(p.label for p in self.providers)

    def stream_chat(self, messages: list[dict], tools: list[dict]) -> Iterator[tuple]:
        from openai import APIError

        last_err: Exception | None = None
        candidates = [p for p in self.providers if _cooling(p.label) == 0] or self.providers[-1:]
        for i, p in enumerate(candidates):
            started = False
            try:
                gen = p.stream(messages, tools)
                first = next(gen)  # ep gui request; loi 429/5xx xuat hien o day
                started = True
                yield ("provider", p.label, p.is_fallback)
                yield first
                yield from gen
                return
            except APIError as e:
                if started:
                    raise
                last_err = e
                secs = _cooldown_for(e)
                if len(self.providers) > 1:
                    _cooldown(p.label, secs)
                log.warning("LLM %s lỗi (%s), %s", p.label, type(e).__name__,
                            "chuyển sang LLM phụ" if i < len(candidates) - 1 else "không còn LLM nào để thử")
        assert last_err is not None
        raise last_err


def build_providers() -> list[Provider]:
    s = settings
    has_fb = bool(s.llm_model_fallback and s.llm_base_url_fallback
                  and (s.llm_api_key_fallback or _is_local(s.llm_base_url_fallback)))
    out = []
    if s.llm_api_key or _is_local(s.llm_base_url):
        # Co LLM phu thi retry it de failover nhanh; khong co thi de SDK cho & thu lai lau hon
        out.append(Provider(s.llm_model, s.llm_base_url, s.llm_api_key, s.llm_model, False, 1 if has_fb else 6))
    if has_fb:
        out.append(Provider(s.llm_model_fallback, s.llm_base_url_fallback, s.llm_api_key_fallback,
                            s.llm_model_fallback, bool(out), 4))
    return out


def default_llm() -> LLM:
    return FailoverLLM(build_providers())
