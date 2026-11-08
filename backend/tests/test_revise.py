"""revise_proposal: sua de xuat PENDING bang cach tao ban moi, ban cu SUPERSEDED; agent van khong the duyet."""
import datetime as dt

import pytest
from sqlalchemy import select

from app.agent import orchestrator
from app.agent import tools as toolmod
from app.agent.tools import ToolContext
from app.models import AuditLog, ChatSession, Proposal, Supplier, User
from app.proposals import builders, service
from app.proposals.service import ProposalError
from tests.test_hitl import ScriptedLLM


def _fresh(db, p):
    # Ngay mo phong (SIM_TODAY) co the cu hon dong ho that -> de xuat vua tao da qua han chot; keo han ra xa.
    p.expires_at = dt.datetime.now() + dt.timedelta(days=1)
    db.commit()


def _mk_po(db):
    """Dat lai moi de xuat PO cua ngay (don PENDING cu co the con tu test khac) roi tao don moi."""
    for p in db.scalars(select(Proposal).where(Proposal.type == "PURCHASE_ORDER")):
        if p.status == "PENDING":
            p.status = "EXPIRED"
        # Go dedupe_key de builder luon tao de xuat MOI (neu khong, no tra lai de xuat cu da EXECUTED tu test khac)
        if p.dedupe_key and not p.dedupe_key.startswith("old-"):
            p.dedupe_key = f"old-{p.id}"
    db.commit()
    for sup in db.scalars(select(Supplier).order_by(Supplier.code)):
        p, _, _ = builders.purchase_order(db, sup, "agent")
        if p:
            _fresh(db, p)
            return p
    pytest.skip("không có NCC nào cần đặt hàng")


def _ctx(db):
    return ToolContext(db=db, user=db.scalar(select(User).where(User.username == "quanly")))


def test_revise_creates_new_pending_and_supersedes_old(db):
    old = _mk_po(db)
    line = old.payload["lines"][0]
    out = toolmod.REGISTRY["revise_proposal"].fn(_ctx(db), proposal_id=old.id, sku_qty=[{"sku": line["sku"], "qty": line["qty"] + 1}])
    assert "error" not in out.data, out.data
    new = db.get(Proposal, out.data["proposal_id"])
    db.refresh(old)
    assert new.id != old.id and new.status == "PENDING" and old.status == "SUPERSEDED"
    assert next(l for l in new.payload["lines"] if l["sku"] == line["sku"])["qty"] == line["qty"] + 1
    assert new.payload["total_value"] == sum(l["qty"] * l["unit_cost"] for l in new.payload["lines"])
    assert new.est_value == new.payload["total_value"]
    actions = {a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "proposal"))}
    assert {"PROPOSAL_SUPERSEDED", "PROPOSAL_REVISED"} <= actions


def test_superseded_cannot_be_approved_or_rejected(db):
    old = _mk_po(db)
    line = old.payload["lines"][0]
    builders.revise(db, old.id, "agent", {line["sku"]: line["qty"] + 1})
    db.commit()
    mgr = db.scalar(select(User).where(User.username == "quanly"))
    with pytest.raises(ProposalError) as e:
        service.approve(db, old.id, mgr)
    assert e.value.status_code == 409
    with pytest.raises(ProposalError):
        service.reject(db, old.id, mgr, "x")
    db.refresh(old)
    assert old.status == "SUPERSEDED"


def test_cannot_revise_non_pending(db):
    old = _mk_po(db)
    for st in ("APPROVED", "EXECUTED", "REJECTED", "SUPERSEDED"):
        old.status = st
        db.commit()
        out = toolmod.REGISTRY["revise_proposal"].fn(_ctx(db), proposal_id=old.id,
                                                    sku_qty=[{"sku": old.payload["lines"][0]["sku"], "qty": old.payload["lines"][0]["qty"] + 1}])
        assert "error" in out.data and st in out.data["error"]
        db.refresh(old)
        assert old.status == st
    old.status = "EXPIRED"
    db.commit()


def test_revise_validates_input(db):
    old = _mk_po(db)
    t = toolmod.REGISTRY["revise_proposal"].fn
    assert "error" in t(_ctx(db), proposal_id=old.id, sku_qty=[{"sku": "NOPE999", "qty": 3}]).data
    assert "error" in t(_ctx(db), proposal_id=old.id, sku_qty=[{"sku": old.payload["lines"][0]["sku"], "qty": -1}]).data
    assert "error" in t(_ctx(db), proposal_id=old.id).data
    assert "error" in t(_ctx(db), proposal_id=999999).data
    db.refresh(old)
    assert old.status == "PENDING"
    old.status = "EXPIRED"
    db.commit()


def test_revise_markdown_pct(db):
    p, _ = builders.markdown(db, "agent", days=7)
    if not p:
        pytest.skip("không có lô nào đáng giảm giá")
    _fresh(db, p)
    out = toolmod.REGISTRY["revise_proposal"].fn(_ctx(db), proposal_id=p.id, markdown_pct=0.3)
    assert "error" not in out.data, out.data
    new = db.get(Proposal, out.data["proposal_id"])
    assert new.status == "PENDING" and all(i["markdown_pct"] == 0.3 for i in new.payload["items"])
    assert "error" in toolmod.REGISTRY["revise_proposal"].fn(_ctx(db), proposal_id=new.id, markdown_pct=0.99).data
    new.status = "EXPIRED"
    db.commit()


def test_llm_cannot_approve_after_revise(db, outbox):
    old = _mk_po(db)
    sku, q0 = old.payload["lines"][0]["sku"], old.payload["lines"][0]["qty"]
    u = db.scalar(select(User).where(User.username == "quanly"))
    s = ChatSession(title="t", username=u.username, created_at=dt.datetime(2026, 11, 7))
    db.add(s)
    db.commit()
    llm = ScriptedLLM([
        {"calls": [("revise_proposal", {"proposal_id": old.id, "sku_qty": [{"sku": sku, "qty": q0 + 1}]}),
                   ("approve_proposal", {"id": old.id})]},
        {"text": "Đã tạo bản sửa, chờ anh/chị duyệt."},
    ])
    ev = list(orchestrator.run_turn(db, s, u, "Giảm còn 2 thùng và duyệt luôn", llm=llm))
    res = [e for e in ev if e["type"] == "tool_result"]
    assert res[0]["ok"] is True, res[0]["error"]
    assert res[1]["ok"] is False
    assert "approve_proposal" not in llm.seen_tools and "revise_proposal" in llm.seen_tools
    db.expire_all()
    assert outbox == []
    new = db.scalar(select(Proposal).where(Proposal.chat_session_id == s.id, Proposal.status == "PENDING"))
    assert new is not None and new.id != old.id
    assert db.get(Proposal, old.id).status == "SUPERSEDED"
    new.status = "EXPIRED"
    db.commit()
