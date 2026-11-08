"""Failover LLM chinh -> LLM phu, cooldown, va xu ly khac biet giua cac provider OpenAI-compatible."""
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from app.agent import llm as llmmod
from app.agent import tools as toolmod


@pytest.fixture(autouse=True)
def _reset_cooldown():
    llmmod._cool_until.clear()
    yield
    llmmod._cool_until.clear()


def rate_limit(msg="Rate limit reached ... tokens per minute (TPM)"):
    return openai.RateLimitError(msg, response=httpx.Response(429, request=httpx.Request("POST", "http://x")), body=None)


class FakeProvider:
    def __init__(self, label, events=None, error=None, error_after=None, is_fallback=False):
        self.label, self.is_fallback = label, is_fallback
        self.events, self.error, self.error_after, self.calls = events or [], error, error_after, 0

    def stream(self, messages, tools):
        self.calls += 1
        if self.error:
            raise self.error
        for i, e in enumerate(self.events):
            if self.error_after is not None and i == self.error_after:
                raise openai.APIConnectionError(request=httpx.Request("POST", "http://x"))
            yield e


def test_falls_back_on_rate_limit_before_any_output():
    primary = FakeProvider("groq", error=rate_limit())
    fb = FakeProvider("gemini", [("text", "xin chào"), ("finish", "stop")], is_fallback=True)
    out = list(llmmod.FailoverLLM([primary, fb]).stream_chat([], []))
    assert out[0] == ("provider", "gemini", True)
    assert ("text", "xin chào") in out


def test_no_switch_after_output_started():
    primary = FakeProvider("groq", [("text", "Đang"), ("text", " trả lời")], error_after=1)
    fb = FakeProvider("gemini", [("text", "khác")], is_fallback=True)
    with pytest.raises(openai.APIConnectionError):
        list(llmmod.FailoverLLM([primary, fb]).stream_chat([], []))
    assert fb.calls == 0  # khong tron 2 cau tra loi


def test_daily_limit_puts_primary_on_long_cooldown():
    primary = FakeProvider("groq", error=rate_limit("Rate limit ... tokens per day (TPD): Limit 200000"))
    fb = FakeProvider("gemini", [("text", "ok")], is_fallback=True)
    llm = llmmod.FailoverLLM([primary, fb])
    list(llm.stream_chat([], []))
    list(llm.stream_chat([], []))
    assert primary.calls == 1  # luot 2 bo qua LLM chinh dang "nghi"
    assert llmmod._cooling("groq") > 600


def test_raises_when_all_providers_fail():
    llm = llmmod.FailoverLLM([FakeProvider("groq", error=rate_limit()), FakeProvider("gemini", error=rate_limit())])
    with pytest.raises(openai.RateLimitError):
        list(llm.stream_chat([], []))


def test_gemini_gets_schema_without_nullable_types():
    tools = toolmod.schemas()
    assert llmmod.supports_nullable_types("https://api.groq.com/openai/v1")
    assert not llmmod.supports_nullable_types("https://generativelanguage.googleapis.com/v1beta/openai/")
    stripped = llmmod.strip_nullable(tools)
    for t in stripped:
        for v in t["function"]["parameters"]["properties"].values():
            assert not isinstance(v.get("type"), list)
    # ban goc khong bi sua
    assert any(isinstance(v.get("type"), list) for t in tools for v in t["function"]["parameters"]["properties"].values())


def test_tool_calls_without_index_are_numbered_by_id():
    """Gemini stream 2 tool call song song khong co `index`: khong duoc gop lam mot."""
    def chunk(tc):
        return NS(choices=[NS(delta=NS(content=None, tool_calls=[tc]), finish_reason=None)])
    chunks = [
        chunk(NS(index=None, id="a", function=NS(name="get_inventory_summary", arguments="{}"))),
        chunk(NS(index=None, id="b", function=NS(name="get_cost_report", arguments="{}"))),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="tool_calls")]),
    ]
    p = llmmod.Provider("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/", "k", "m", True, 0)
    p.client = NS(chat=NS(completions=NS(create=lambda **kw: iter(chunks))))
    calls = [e for e in p.stream([], []) if e[0] == "tool_call"]
    assert [(c[1], c[3]) for c in calls] == [(0, "get_inventory_summary"), (1, "get_cost_report")]


def test_thought_signature_kept_for_gemini_and_stripped_for_others():
    sig = {"google": {"thought_signature": "abc"}}
    msgs = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "type": "function", "function": {"name": "a", "arguments": "{}"}, "extra_content": sig},
        {"id": "2", "type": "function", "function": {"name": "b", "arguments": "{}"}},  # do Groq tao, khong co chu ky
    ]}]
    g = llmmod.adapt_messages(msgs, "https://generativelanguage.googleapis.com/v1beta/openai/")
    assert g[0]["tool_calls"][0]["extra_content"] == sig
    assert g[0]["tool_calls"][1]["extra_content"]["google"]["thought_signature"] == llmmod.DUMMY_THOUGHT_SIGNATURE
    o = llmmod.adapt_messages(msgs, "https://api.groq.com/openai/v1")
    assert all("extra_content" not in tc for tc in o[0]["tool_calls"])
    assert "extra_content" not in msgs[0]["tool_calls"][1]  # khong sua ban goc
