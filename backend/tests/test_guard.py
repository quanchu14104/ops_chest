"""Kiem tra grounding o runtime + do luong luot hoi dap (audit AGENT_TURN)."""
import datetime
import json

from sqlalchemy import select

from app.agent import orchestrator
from app.agent.guard import check_answer
from app.models import AuditLog, ChatMessage, ChatSession, User


class LLM:
    def __init__(self, steps):
        self.steps = list(steps)

    def stream_chat(self, messages, tools):
        step = self.steps.pop(0)
        yield ("provider", "fake-model", False)
        if step.get("text"):
            yield ("text", step["text"])
        for i, (name, args) in enumerate(step.get("calls", [])):
            yield ("tool_call", i, f"c{i}", name, json.dumps(args))
        if step.get("usage"):
            yield ("usage", *step["usage"])
        yield ("finish", "stop")


def _session(db):
    u = db.scalar(select(User).where(User.username == "quanly"))
    s = ChatSession(title="t", username=u.username, created_at=datetime.datetime(2026, 11, 7))
    db.add(s)
    db.commit()
    return s, u


def test_check_answer_unit():
    assert check_answer("Tồn kho 1.250.000đ", ["value:1250000"]).ok
    r = check_answer("Doanh thu 9.999.000đ", ["value:1250000"])
    assert r.ungrounded_numbers == ["9.999.000"] and not r.false_exec
    assert check_answer("Em đã gửi email cho nhà cung cấp.", []).false_exec
    assert check_answer("Năm 2026 có 365 ngày", []).ok  # nam & so nho khong bi bat


def test_invented_number_emits_guard_and_is_persisted(db):
    s, u = _session(db)
    llm = LLM([{"calls": [("get_inventory_summary", {})], "usage": (100, 10)},
               {"text": "Tồn kho trị giá 987.654.321đ.", "usage": (200, 20)}])
    events = list(orchestrator.run_turn(db, s, u, "Kho thế nào?", llm=llm))
    g = next(e for e in events if e["type"] == "guard")
    assert g["ungrounded_numbers"] == ["987.654.321"]
    last = db.scalars(select(ChatMessage).where(ChatMessage.session_id == s.id, ChatMessage.role == "assistant")
                      .order_by(ChatMessage.id.desc())).first()
    assert last.ui_events and last.ui_events[0]["type"] == "guard"  # tai lai lich su van thay canh bao


def test_grounded_answer_has_no_guard(db):
    s, u = _session(db)
    llm = LLM([{"text": "Anh/chị hỏi mốc 12.345 nhé."}])  # so xuat hien trong cau hoi cua user
    events = list(orchestrator.run_turn(db, s, u, "Cho tôi biết về mốc 12.345", llm=llm))
    assert not any(e["type"] == "guard" for e in events)


def test_turn_metrics_written_to_audit(db):
    s, u = _session(db)
    llm = LLM([{"calls": [("get_inventory_summary", {}), ("khong_ton_tai", {})], "usage": (100, 10)},
               {"text": "Xong.", "usage": (200, 20)}])
    events = list(orchestrator.run_turn(db, s, u, "Kho thế nào?", llm=llm))
    done = events[-1]
    assert done["type"] == "done"
    m = done["metrics"]
    assert m["rounds"] == 2 and m["prompt_tokens"] == 300 and m["completion_tokens"] == 30
    assert m["usage_reported"] and m["tool_errors"] == 1 and m["models"] == ["fake-model"]
    row = db.scalar(select(AuditLog).where(AuditLog.action == "AGENT_TURN", AuditLog.entity_id == str(s.id)))
    assert row.actor == "quanly" and row.detail["prompt_tokens"] == 300 and row.detail["outcome"] == "ok"
    assert row.detail["tools"] == ["get_inventory_summary", "khong_ton_tai"]


def test_no_usage_from_provider_is_reported_as_unknown(db):
    s, u = _session(db)
    events = list(orchestrator.run_turn(db, s, u, "xin chào", llm=LLM([{"text": "Chào anh/chị."}])))
    assert events[-1]["metrics"]["usage_reported"] is False
