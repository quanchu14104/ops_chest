"""Tua nhanh lam thay doi DB va dong ho dung chung, nen file nay co ten de chay SAU CUNG."""
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app import clock
from app.clock import today
from app.models import AppMeta, DailySales, DemandHypothesis, Lot, Product, Proposal, PurchaseOrder
from app.services.history import load_history
from app.sim.advance import advance


@pytest.fixture()
def restore_clock(db):
    yield
    clock.set_today(None)
    row = db.get(AppMeta, clock.SIM_CLOCK_KEY)
    if row:
        db.delete(row)
        db.commit()


def test_advance_writes_sales_but_decides_nothing(db, restore_clock):
    start = today()
    executed = db.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "EXECUTED"))
    out = advance(db, 2, "quanly")
    assert today() == start + timedelta(days=2)
    assert db.get(AppMeta, clock.SIM_CLOCK_KEY).value == today().isoformat()
    assert db.scalar(select(func.count()).select_from(DailySales).where(DailySales.date == start)) > 0
    assert out["totals"]["sold"] > 0
    assert db.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "EXECUTED")) == executed
    assert db.scalar(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.status == "SENT", PurchaseOrder.expected_date < start)) == 0


def test_hypothesis_is_scored_when_window_passes(db, restore_clock):
    p = db.scalar(select(Product).where(Product.status == "ACTIVE", Product.category.ilike("%Bia%")))
    t = today()
    row = DemandHypothesis(sku=p.sku, category=None, factor=1.5, start_date=t, end_date=t, reason="Thử", status="ACTIVE",
                           baseline_total=1.0, created_by="quanly", created_at=clock.now().replace(tzinfo=None))
    db.add(row)
    db.commit()
    out = advance(db, 1, "quanly")
    db.refresh(row)
    assert row.status == "EVALUATED" and row.result["verdict"] in ("CORRECT", "PARTIAL", "WRONG")
    assert any(x["id"] == row.id for x in out["hypotheses_evaluated"])


def test_rejects_too_many_days(db):
    with pytest.raises(ValueError):
        advance(db, 99, "quanly")


def test_unanswered_proposals_expire(db, restore_clock):
    t = clock.now().replace(tzinfo=None)
    p = Proposal(type="DISPOSE", status="PENDING", title="t", rationale="r", evidence={}, payload={"items": []},
                 original_payload={"items": []}, created_by="job", created_at=t,
                 expires_at=t.replace(hour=23, minute=59))
    db.add(p)
    db.commit()
    out = advance(db, 1, "quanly")
    db.refresh(p)
    assert p.status == "EXPIRED" and out["proposals_expired_unanswered"] >= 1


def test_markdown_sales_do_not_count_as_demand(db, restore_clock):
    t = today()
    for lot in db.scalars(select(Lot).where(Lot.status == "ACTIVE", Lot.qty_remaining > 0, Lot.expiry_date > t)):
        lot.markdown_pct = 0.3
    db.commit()
    advance(db, 1, "quanly")
    rows = db.scalars(select(DailySales).where(DailySales.date == t, DailySales.discounted_qty > 0)).all()
    assert rows and all(r.discounted_qty <= r.qty_sold for r in rows)
    clock.set_today(t + timedelta(days=1))
    h = load_history(db)
    r = max(rows, key=lambda x: x.discounted_qty)
    assert h.demand[r.product_id][-1] < h.sales[r.product_id][-1]
