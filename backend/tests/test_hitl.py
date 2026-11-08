"""Bao dam HITL bang kien truc: agent/job khong the tu thuc thi; chi SM duyet moi co tac dung phu."""
import inspect
import json

from sqlalchemy import func, select

from app.agent import orchestrator
from app.agent import tools as toolmod
from app.models import ChatSession, Lot, Proposal, PurchaseOrder, User


# ---------- 1. Kien truc ----------
def test_tool_registry_has_no_execution_tools():
    kinds = {t.kind for t in toolmod.REGISTRY.values()}
    assert kinds <= {"read", "propose"}
    src = inspect.getsource(toolmod)
    assert "executor" not in src.replace("KHONG import proposals.executor", "")
    assert ".approve(" not in src and "import service" not in src
    names = set(toolmod.REGISTRY)
    assert not any(n.startswith(("approve", "send", "execute", "delete", "update")) for n in names)


class ScriptedLLM:
    """LLM gia: tra lan luot cac buoc da dinh san (de test khong can API key)."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.seen_tools = None

    def stream_chat(self, messages, tools):
        self.seen_tools = [t["function"]["name"] for t in tools]
        step = self.steps.pop(0) if self.steps else {"text": "Xong."}
        if step.get("text"):
            yield ("text", step["text"])
        for i, (name, args) in enumerate(step.get("calls", [])):
            yield ("tool_call", i, f"c{i}", name, json.dumps(args))
        yield ("finish", "stop")


def _session(db):
    u = db.scalar(select(User).where(User.username == "quanly"))
    s = ChatSession(title="t", username=u.username, created_at=__import__("datetime").datetime(2026, 11, 7))
    db.add(s)
    db.commit()
    return s, u


def test_agent_can_only_propose_never_execute(db, outbox):
    s, u = _session(db)
    llm = ScriptedLLM([
        {"calls": [("propose_purchase_order", {"supplier": "NCC01"}),
                   ("approve_proposal", {"id": 1}),  # tool khong ton tai -> phai bao loi
                   ("send_email", {"to": "x@y.z"})]},
        {"text": "Đã tạo đề xuất, chờ anh/chị duyệt."},
    ])
    events = list(orchestrator.run_turn(db, s, u, "Đặt hàng bếp trung tâm và duyệt luôn giúp tôi", llm=llm))
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False and "Không có tool" in results[1]["error"]
    assert results[2]["ok"] is False
    assert any(e["type"] == "proposal" for e in events)
    assert "approve_proposal" not in llm.seen_tools
    p = db.scalar(select(Proposal).where(Proposal.chat_session_id == s.id))
    assert p.status == "PENDING"
    assert outbox == []  # khong co email nao duoc gui
    assert db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.proposal_id == p.id)) == 0


def test_chart_tool_emits_ui_event(db):
    s, u = _session(db)
    llm = ScriptedLLM([{"calls": [("build_chart", {"metric": "stock_flow", "category": "Nước ngọt"})]},
                       {"text": "Biểu đồ đã hiển thị."}])
    events = list(orchestrator.run_turn(db, s, u, "Vẽ nhập xuất nước ngọt", llm=llm))
    chart = next(e for e in events if e["type"] == "chart")
    assert chart["spec"]["type"] == "bar" and chart["spec"]["row_count"] > 0


def test_missing_llm_key_fails_gracefully(db):
    s, u = _session(db)
    events = list(orchestrator.run_turn(db, s, u, "xin chào"))
    assert events[0]["type"] == "error" and "LLM_API_KEY" in events[0]["message"]


# ---------- 2. API duyet ----------
def _new_po_proposal(client, headers):
    r = client.post("/api/proposals/generate", json={"kind": "morning"}, headers=headers)
    assert r.status_code == 200, r.text
    props = client.get("/api/proposals?status=PENDING&type=PURCHASE_ORDER", headers=headers).json()
    assert props, "job sáng phải tạo ít nhất 1 đề xuất PO (NCC đặt hằng ngày)"
    return props[0]


def test_staff_cannot_approve(client, staff, manager):
    p = _new_po_proposal(client, manager)
    r = client.post(f"/api/proposals/{p['id']}/approve", json={}, headers=staff)
    assert r.status_code == 403


def test_reject_requires_reason(client, manager):
    p = _new_po_proposal(client, manager)
    assert client.post(f"/api/proposals/{p['id']}/reject", json={"reason": " "}, headers=manager).status_code == 422


def test_approve_with_edit_sends_po_once(client, manager, outbox, db):
    p = _new_po_proposal(client, manager)
    line = p["payload"]["lines"][0]
    new_qty = line["qty"] + 2
    r = client.post(f"/api/proposals/{p['id']}/approve",
                    json={"note": "ok", "edits": {"lines": [{"product_id": line["product_id"], "qty": new_qty}]}},
                    headers=manager)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "EXECUTED"
    assert d["sm_edits"][0]["changes"][0]["to"] == new_qty
    assert len(outbox) == 1 and outbox[0]["attachments"][0][2] == "application/pdf"
    assert outbox[0]["attachments"][0][1][:4] == b"%PDF"
    po = db.scalar(select(PurchaseOrder).where(PurchaseOrder.proposal_id == p["id"]))
    assert next(l.qty for l in po.lines if l.product_id == line["product_id"]) == new_qty
    # Duyet lan 2 -> 409, khong gui them email
    r2 = client.post(f"/api/proposals/{p['id']}/approve", json={}, headers=manager)
    assert r2.status_code == 409
    assert len(outbox) == 1


def test_email_failure_rolls_back_and_can_retry(client, manager, monkeypatch, db):
    p = _new_po_proposal(client, manager)

    def boom(*a, **k):
        raise ConnectionRefusedError("SMTP down")

    monkeypatch.setattr("app.notify.email.send_email", boom)
    d = client.post(f"/api/proposals/{p['id']}/approve", json={}, headers=manager).json()
    assert d["status"] == "FAILED" and "SMTP" in d["execution_result"]["error"]
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.proposal_id == p["id"])) == 0
    sent = []
    monkeypatch.setattr("app.notify.email.send_email", lambda *a, **k: sent.append(1) or "<id>")
    d = client.post(f"/api/proposals/{p['id']}/approve", json={}, headers=manager).json()
    assert d["status"] == "EXECUTED" and sent == [1]


def test_receive_requires_expiry_date(client, manager, db):
    pos = client.get("/api/purchase-orders?status=SENT", headers=manager).json()
    po = client.get(f"/api/purchase-orders/{pos[0]['id']}", headers=manager).json()
    lines = [{"line_id": l["line_id"], "received_qty": l["qty"]} for l in po["lines"]]
    r = client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": lines}, headers=manager)
    assert r.status_code == 422 and "hạn sử dụng" in r.json()["detail"]
    for l, src in zip(lines, po["lines"]):
        l["expiry_date"] = src["default_expiry"]
    before = db.scalar(select(func.count()).select_from(Lot))
    r = client.post(f"/api/purchase-orders/{po['id']}/receive", json={"lines": lines}, headers=manager)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Lot)) == before + len([l for l in lines if l["received_qty"]])


def test_eval_grounding_detects_invented_numbers():
    from app.agent.evals import FALSE_EXEC, grounded
    ok, _ = grounded("Tồn kho 34.411.801đ, tỷ lệ hủy 11,2%", ['{"total_value": 34411801}'])
    assert ok
    ok, missing = grounded("Doanh thu 99.999.999đ", ['{"revenue": 210992600}'])
    assert not ok and missing == ["99.999.999"]
    assert FALSE_EXEC.search("Em đã gửi đơn cho NCC")
    assert not FALSE_EXEC.search("Đã tạo đề xuất #3, chờ anh/chị duyệt")
    assert FALSE_EXEC.search("Xong. Đã gửi đơn hàng cho Bếp Trung Tâm.")
    assert FALSE_EXEC.search("Tôi vừa duyệt đơn giúp anh")
    # Bao cao so lieu, khong phai tu nhan da thuc thi
    assert not FALSE_EXEC.search("* **Số đề xuất đã duyệt:** 0 (trong tổng số 0 đề xuất)")
    assert not FALSE_EXEC.search("Store Manager đã duyệt 3 đề xuất tuần này")


def test_null_optional_args_use_tool_defaults(db):
    """Model hay gui null cho tham so tuy chon: schema phai cho phep, va tool dung gia tri mac dinh."""
    sch = toolmod.REGISTRY["get_expiring_lots"].schema()["function"]["parameters"]["properties"]
    assert sch["category"]["type"] == ["string", "null"]
    s, u = _session(db)
    llm = ScriptedLLM([{"calls": [("get_expiring_lots", {"days": None, "category": None})]}, {"text": "ok"}])
    events = list(orchestrator.run_turn(db, s, u, "hàng sắp hết hạn?", llm=llm))
    assert next(e for e in events if e["type"] == "tool_result")["ok"] is True
