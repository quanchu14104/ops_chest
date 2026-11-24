"""Lenh nhanh trong chat: mo the tac vu khong qua LLM, ghi vao hoi thoai, khong bao gio tu thuc hien."""
import inspect

from sqlalchemy import select

from app.models import Proposal
from app.services import commands


def _session(client, headers) -> int:
    return client.post("/api/chat/sessions", headers=headers, json={}).json()["id"]


def test_commands_module_never_executes():
    src = inspect.getsource(commands)
    assert "executor" not in src.replace("KHONG import proposals.executor", "")
    assert ".approve(" not in src and "proposals import service" not in src
    for _, tool_name, _ in commands.COMMANDS.values():
        assert commands.toolmod.REGISTRY[tool_name].kind in ("read", "propose")


def test_command_opens_card_and_is_saved_in_thread(client, manager):
    sid = _session(client, manager)
    r = client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "pending"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Đề xuất chờ duyệt"
    assert body["ui"] == [{"type": "widget", "kind": "panel", "panel": "inbox", "title": "Đề xuất chờ duyệt",
                           "params": {"type": None}}]
    msgs = client.get(f"/api/chat/sessions/{sid}", headers=manager).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[0]["content"] == "▸ Đề xuất chờ duyệt"
    assert msgs[1]["name"] == "command" and msgs[1]["tool_calls"][0]["name"] == "open_approval_inbox"
    assert msgs[2]["ui_events"][0]["panel"] == "inbox"
    # Phien moi lay ten theo lenh dau tien
    assert any(s["id"] == sid and s["title"] == "Đề xuất chờ duyệt"
               for s in client.get("/api/chat/sessions", headers=manager).json())


def test_command_args_and_forms(client, manager):
    sid = _session(client, manager)
    lots = client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "lots:7"}).json()
    assert lots["ui"][0]["panel"] == "lots" and lots["ui"][0]["params"] == {"days": 7}
    pull = client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "pull"}).json()
    assert pull["ui"][0]["kind"] in ("form", "table")
    typed = client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "pending:MARKDOWN"}).json()
    assert typed["ui"][0]["params"] == {"type": "MARKDOWN"}


def test_command_errors(client, manager, staff):
    sid = _session(client, manager)
    assert client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "nope"}).status_code == 404
    assert client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "receive"}).status_code == 404
    # Khong chay lenh tren hoi thoai cua nguoi khac
    assert client.post(f"/api/chat/sessions/{sid}/command", headers=staff, json={"key": "pending"}).status_code == 404
    # Tool bao loi (vd don khong ton tai) -> hien trong chat, khong 500
    r = client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "receive:999999"})
    assert r.status_code == 200 and r.json()["error"]


def test_order_command_only_creates_pending_proposal(client, manager, db):
    sid = _session(client, manager)
    r = client.post(f"/api/chat/sessions/{sid}/command", headers=manager, json={"key": "order:NCC01"})
    assert r.status_code == 200, r.text
    created = db.scalars(select(Proposal).where(Proposal.chat_session_id == sid)).all()
    for u in r.json()["ui"]:
        if u["type"] == "proposal":
            p = db.get(Proposal, u["proposal"]["id"])
            assert p.status == "PENDING" and p.executed_at is None
    assert all(p.status == "PENDING" for p in created)
    # Don de xuat do lenh nay tao: test khac (vd test_hitl) can tu tao de xuat NCC01 trong hoi thoai cua no
    for p in created:
        db.delete(p)
    db.commit()
