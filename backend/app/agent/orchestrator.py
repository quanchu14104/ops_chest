"""Vong lap agent tu viet (khong framework) de de debug va trinh bay.

Moi luot: LLM -> (tool calls -> ket qua tool -> LLM)* -> tra loi. Toi da `llm_max_tool_rounds` vong.
Phat su kien cho UI qua generator: token / tool_call / tool_result / chart / proposal / done / error.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app import audit
from app.agent import tools as toolmod
from app.agent.guard import check_answer
from app.agent.llm import LLM, LLMNotConfigured, default_llm
from app.agent.prompts import system_prompt
from app.clock import now
from app.config import settings
from app.models import ChatMessage, ChatSession, User

log = logging.getLogger(__name__)
MAX_TOOL_RESULT_CHARS = 8000
HISTORY_MESSAGES = 24
OLD_TOOL_RESULT_CHARS = 400  # ket qua tool cua cac luot truoc chi giu phan dau


def _now() -> datetime:
    return now().replace(tzinfo=None)


def _prune(o):
    """Bo null/rong va lam tron so thuc: ket qua tool gui cho LLM cang gon cang it token."""
    if isinstance(o, dict):
        return {k: _prune(v) for k, v in o.items() if v not in (None, "", [], {})}
    if isinstance(o, list):
        return [_prune(v) for v in o]
    if isinstance(o, float):
        return round(o, 3) if abs(o) < 100 else round(o)
    return o


def _dump(obj) -> str:
    s = json.dumps(_prune(obj), ensure_ascii=False, default=str, separators=(",", ":"))
    if len(s) > MAX_TOOL_RESULT_CHARS:
        s = s[:MAX_TOOL_RESULT_CHARS] + '..."[truncated: narrow the query]"'
    return s


def history_messages(session: ChatSession) -> list[dict]:
    msgs = session.messages[-HISTORY_MESSAGES:]
    # Khong cat giua chung assistant(tool_calls) va tool results: bat dau tu tin nhan user
    while msgs and msgs[0].role != "user":
        msgs = msgs[1:]
    out = []
    for m in msgs:
        if m.role == "user":
            out.append({"role": "user", "content": m.content or ""})
        elif m.role == "assistant":
            d = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                d["tool_calls"] = m.tool_calls
            out.append(d)
        elif m.role == "tool":
            # Ket qua tool cua luot truoc: chi giu phan dau (can thi agent goi lai tool) -> tiet kiem token
            c = m.content or ""
            if len(c) > OLD_TOOL_RESULT_CHARS:
                c = c[:OLD_TOOL_RESULT_CHARS] + "...[older result truncated; call the tool again if needed]"
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": c})
    return out


@dataclass
class TurnStats:
    """Do luong mot luot hoi dap: ghi vao audit_log (action AGENT_TURN) de theo doi chi phi/do tre/chat luong."""
    t0: float = field(default_factory=time.perf_counter)
    llm_seconds: float = 0.0
    rounds: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_reported: bool = False
    models: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    tool_errors: int = 0
    ungrounded_numbers: list[str] = field(default_factory=list)
    false_exec: bool = False


def _finish(db: Session, session: ChatSession, user: User, st: TurnStats, outcome: str) -> dict:
    """Ghi audit + tra ve metrics cho su kien `done`. Loi ghi audit khong duoc lam hong cau tra loi."""
    m = {"seconds": round(time.perf_counter() - st.t0, 2), "llm_seconds": round(st.llm_seconds, 2),
         "rounds": st.rounds, "prompt_tokens": st.prompt_tokens, "completion_tokens": st.completion_tokens,
         "usage_reported": st.usage_reported, "models": st.models, "tools": st.tools,
         "tool_errors": st.tool_errors, "ungrounded_numbers": st.ungrounded_numbers,
         "false_exec": st.false_exec, "outcome": outcome}
    try:
        audit.log(db, user.username, "AGENT_TURN", "chat_session", session.id, m)
        db.commit()
    except Exception:  # noqa: BLE001
        log.exception("Khong ghi duoc audit AGENT_TURN")
        db.rollback()
    return m


def run_turn(db: Session, session: ChatSession, user: User, text: str, llm: LLM | None = None) -> Iterator[dict]:
    db.add(ChatMessage(session_id=session.id, role="user", content=text, created_at=_now()))
    db.commit()
    db.refresh(session)
    try:
        llm = llm or default_llm()
    except LLMNotConfigured as e:
        msg = (f"⚠️ {e}. Mở file `.env`, đặt LLM_BASE_URL / LLM_API_KEY / LLM_MODEL (bất kỳ endpoint "
               "OpenAI-compatible nào) rồi khởi động lại backend.")
        db.add(ChatMessage(session_id=session.id, role="assistant", content=msg, created_at=_now()))
        db.commit()
        yield {"type": "error", "message": msg}
        yield {"type": "done"}
        return

    st = TurnStats()
    ctx = toolmod.ToolContext(db=db, user=user, chat_session_id=session.id)
    schemas = toolmod.schemas()
    messages = [{"role": "system", "content": system_prompt(user.full_name, user.role)}] + history_messages(session)

    for round_no in range(settings.llm_max_tool_rounds + 1):
        use_tools = round_no < settings.llm_max_tool_rounds
        text_buf: list[str] = []
        calls: dict[int, dict] = {}
        model_used = None
        t_llm = time.perf_counter()
        try:
            for ev in llm.stream_chat(messages, schemas if use_tools else []):
                if ev[0] == "usage":
                    st.usage_reported = True
                    st.prompt_tokens += ev[1]
                    st.completion_tokens += ev[2]
                elif ev[0] == "provider":
                    model_used = ev[1]
                    if ev[1] not in st.models:
                        st.models.append(ev[1])
                    yield {"type": "provider", "model": ev[1], "fallback": bool(ev[2])}
                elif ev[0] == "text":
                    text_buf.append(ev[1])
                    yield {"type": "token", "text": ev[1]}
                elif ev[0] == "tool_call":
                    _, idx, cid, name, frag, *rest = ev
                    c = calls.setdefault(idx, {"id": None, "name": "", "args": "", "extra": None})
                    if cid:
                        c["id"] = cid
                    if name:
                        c["name"] = name
                    c["args"] += frag or ""
                    if rest and rest[0]:
                        c["extra"] = rest[0]  # vd thought_signature cua Gemini, phai gui lai o luot sau
        except Exception as e:  # noqa: BLE001
            log.exception("LLM error")
            st.llm_seconds += time.perf_counter() - t_llm
            st.rounds += 1
            msg = f"Lỗi khi gọi LLM ({type(e).__name__}): {e}"
            db.add(ChatMessage(session_id=session.id, role="assistant", content=msg, created_at=_now()))
            db.commit()
            yield {"type": "error", "message": msg}
            yield {"type": "done", "metrics": _finish(db, session, user, st, "llm_error")}
            return
        st.llm_seconds += time.perf_counter() - t_llm
        st.rounds += 1

        content = "".join(text_buf)
        tool_calls = [
            {"id": c["id"] or f"call_{round_no}_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": c["args"] or "{}"},
             **({"extra_content": c["extra"]} if c["extra"] else {})}
            for i, c in sorted(calls.items())
        ]
        # Cau tra loi cuoi (khong con tool call): kiem tra so lieu co can cu + co noi sai la da thuc thi khong
        guard_ev: list[dict] = []
        if not tool_calls and content:
            sources = [m["content"] or "" for m in messages if m["role"] in ("tool", "user")]
            res = check_answer(content, sources)
            st.ungrounded_numbers, st.false_exec = res.ungrounded_numbers, res.false_exec
            if not res.ok:
                guard_ev = [res.event()]
        db.add(ChatMessage(session_id=session.id, role="assistant", content=content, name=model_used,
                           tool_calls=tool_calls or None, ui_events=guard_ev or None, created_at=_now()))
        db.commit()
        messages.append({"role": "assistant", "content": content, **({"tool_calls": tool_calls} if tool_calls else {})})
        if not tool_calls:
            for g in guard_ev:
                yield g
            yield {"type": "done", "metrics": _finish(db, session, user, st, "ok")}
            return

        for tc in tool_calls:
            name = tc["function"]["name"]
            t = toolmod.REGISTRY.get(name)
            ui: list[dict] = []
            result = None
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments phải là object JSON")
            except Exception as e:  # noqa: BLE001
                args, result = {}, {"error": f"Tham số JSON không hợp lệ: {e}"}
            yield {"type": "tool_call", "id": tc["id"], "name": name, "args": args,
                   "kind": t.kind if t else None}
            if result is not None:
                pass
            elif t is None:
                result = {"error": f"Không có tool tên {name}"}
            else:
                try:
                    # null = "khong dat" -> dung gia tri mac dinh cua tool
                    out = t.fn(ctx, **{k: v for k, v in args.items() if v is not None})
                    result, ui = out.data, out.ui
                except TypeError as e:
                    db.rollback()
                    result = {"error": f"Sai tham số cho {name}: {e}"}
                except Exception as e:  # noqa: BLE001
                    log.exception("Tool %s error", name)
                    db.rollback()
                    result = {"error": f"{type(e).__name__}: {e}"}
            for u in ui:
                yield u
            ok = not (isinstance(result, dict) and "error" in result)
            st.tools.append(name)
            st.tool_errors += 0 if ok else 1
            yield {"type": "tool_result", "id": tc["id"], "name": name, "ok": ok,
                   "error": None if ok else result.get("error")}
            content = _dump(result)
            db.add(ChatMessage(session_id=session.id, role="tool", tool_call_id=tc["id"], name=name,
                               content=content, ui_events=ui or None, created_at=_now()))
            db.commit()
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})

    yield {"type": "done", "metrics": _finish(db, session, user, st, "max_rounds")}
