"""Duong du phong khong can LLM: /api/chat/quick tra widget tu tool doc, khong ghi gi."""
import pytest
from sqlalchemy import func, select

from app.models import Proposal
from app.services import quick as quick_svc


def test_quick_requires_login(client):
    assert client.get("/api/chat/quick/inventory").status_code in (401, 403)


@pytest.mark.parametrize("key", list(quick_svc.QUICK))
def test_every_quick_key_returns_widgets(client, manager, key):
    r = client.get(f"/api/chat/quick/{key}", headers=manager)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["key"] == key and d["title"] and d["ui"]
    assert all(u["type"] == "widget" and u["kind"] in ("table", "kpis") for u in d["ui"])


def test_reorder_quick_and_unknown(client, manager):
    assert client.get("/api/chat/quick/reorder:NCC01", headers=manager).status_code == 200
    assert client.get("/api/chat/quick/reorder:NOPE", headers=manager).status_code == 404
    assert client.get("/api/chat/quick/drop_table", headers=manager).status_code == 404


def test_quick_never_creates_proposals_and_staff_can_use(client, staff, db):
    before = db.scalar(select(func.count()).select_from(Proposal))
    for key in ("inventory", "expiring", "pending", "reorder:NCC01"):
        assert client.get(f"/api/chat/quick/{key}", headers=staff).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Proposal)) == before


def test_quick_only_runs_read_tools():
    from app.agent import tools as toolmod
    for _, tool_name, _ in quick_svc.QUICK.values():
        assert toolmod.REGISTRY[tool_name].kind == "read"
