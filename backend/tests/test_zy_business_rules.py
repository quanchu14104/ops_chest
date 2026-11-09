"""Quy tac nghiep vu: chong dat/tra trung, PO tre, KPI tra hang, hop dong het han, gio vang, cham gia thuyet."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app import clock
from app.agent import tools as toolmod
from app.engines.disposition import DispositionInput, evaluate
from app.engines.forecast import Forecast, hypothesis_verdict
from app.engines.replenishment import Incoming, LotState, ReplenishmentInput, compute_order
from app.models import Lot, Product, Proposal, PurchaseOrder, StockMovement, Supplier, SupplierAgreement, User
from app.proposals import builders, service
from app.services import replenish, reports
from app.services.history import forecast_for
from app.services.inventory import on_order

T = date(2026, 11, 7)


@pytest.fixture(autouse=True)
def _restore_clock():
    yield
    clock.set_today(None)


def _mgr(db):
    return db.scalar(select(User).where(User.username == "quanly"))


def _staff(db):
    return db.scalar(select(User).where(User.username == "nhanvien"))


def _only_lot(db, product, qty, expiry, markdown=0.0):
    for lot in db.scalars(select(Lot).where(Lot.product_id == product.id, Lot.status == "ACTIVE")):
        lot.qty_remaining, lot.status = 0, "SOLD"
    lot = Lot(product_id=product.id, qty_received=qty, qty_remaining=qty, received_date=T, expiry_date=expiry,
              unit_cost=product.unit_cost, markdown_pct=markdown, status="ACTIVE")
    db.add(lot)
    db.commit()
    return lot


def _first_product(db, **where):
    q = select(Product).where(Product.status == "ACTIVE").order_by(Product.sku)
    for k, v in where.items():
        q = q.where(getattr(Product, k) == v)
    return db.scalars(q).first()


def _clear_open(db, *types):
    for p in db.scalars(select(Proposal).where(Proposal.type.in_(types), Proposal.status.in_(["PENDING", "FAILED"]))):
        p.status = "EXPIRED"
    for p in db.scalars(select(Proposal).where(Proposal.type.in_(types), Proposal.dedupe_key.is_not(None))):
        p.dedupe_key = None
    db.commit()


def _failing_po(db, monkeypatch, code="NCC01"):
    _clear_open(db, "PURCHASE_ORDER")
    supplier = replenish.get_supplier(db, code)
    p, created, _ = builders.purchase_order(db, supplier, "job")
    db.commit()
    assert p and created
    import app.notify.email as E

    def boom(*a, **k):
        raise RuntimeError("SMTP down")
    good = E.send_email
    monkeypatch.setattr(E, "send_email", boom)
    assert service.approve(db, p.id, _mgr(db)).status == "FAILED"
    monkeypatch.setattr(E, "send_email", good)
    return p, supplier


def test_failed_po_blocks_a_second_order_the_same_day(db, outbox, monkeypatch):
    failed, supplier = _failing_po(db, monkeypatch)
    again, created, _ = builders.purchase_order(db, supplier, "job")
    assert again.id == failed.id and created is False


def test_failed_proposal_expires_like_a_pending_one(db, outbox, monkeypatch):
    failed, _ = _failing_po(db, monkeypatch)
    clock.set_today(T + timedelta(days=5))
    with pytest.raises(service.ProposalError) as e:
        service.approve(db, failed.id, _mgr(db))
    assert e.value.status_code == 409
    db.refresh(failed)
    assert failed.status == "EXPIRED" and outbox == []


def test_expire_stale_sweeps_failed(db, outbox, monkeypatch):
    failed, _ = _failing_po(db, monkeypatch)
    clock.set_today(T + timedelta(days=1))
    service.expire_stale(db)
    db.refresh(failed)
    assert failed.status == "EXPIRED"


def _at_risk_return_lot(db):
    supplier = db.scalar(select(Supplier).where(Supplier.code == "NCC07"))
    product = _first_product(db, supplier_id=supplier.id)
    expiry = T + timedelta(days=supplier.agreements[0].return_min_days_before_expiry + 5)
    sellable = sum(forecast_for(db, product, horizon=(expiry - T).days + 1, start=T).daily)
    return _only_lot(db, product, int(sellable * 1.5), expiry)


def test_return_is_not_proposed_again_while_one_is_open(db, outbox):
    _clear_open(db, "RETURN")
    lot = _at_risk_return_lot(db)
    (first, created), = builders.supplier_return(db, "job", lot_ids=[lot.id])
    db.commit()
    assert created
    clock.set_today(T + timedelta(days=1))
    (again, created), = builders.supplier_return(db, "job", lot_ids=[lot.id])
    assert again.id == first.id and created is False


def test_lot_can_be_returned_again_after_the_open_proposal_closes(db, outbox):
    _clear_open(db, "RETURN")
    lot = _at_risk_return_lot(db)
    (first, _), = builders.supplier_return(db, "job", lot_ids=[lot.id])
    db.commit()
    assert service.reject(db, first.id, _mgr(db), "Chưa muốn trả").status == "REJECTED"
    clock.set_today(T + timedelta(days=1))
    (again, created), = builders.supplier_return(db, "job", lot_ids=[lot.id])
    assert created and again.id != first.id


def test_dispose_only_covers_lots_not_already_proposed(db, outbox):
    _clear_open(db, "DISPOSE")
    for lot in db.scalars(select(Lot).where(Lot.status == "ACTIVE", Lot.expiry_date < T + timedelta(days=3))):
        lot.status = "SOLD"
    db.commit()
    a = _only_lot(db, _first_product(db, freshness_class="SHORT"), 5, T - timedelta(days=1))
    first, created = builders.dispose_expired(db, "job")
    db.commit()
    assert created and [i["lot_id"] for i in first.payload["items"]] == [a.id]

    clock.set_today(T + timedelta(days=1))
    same, created = builders.dispose_expired(db, "job")
    assert same.id == first.id and created is False

    b = _only_lot(db, _first_product(db, freshness_class="LONG"), 4, T)
    second, created = builders.dispose_expired(db, "job")
    db.commit()
    assert created and [i["lot_id"] for i in second.payload["items"]] == [b.id]
    assert service.approve(db, second.id, _mgr(db)).status == "EXECUTED"
    assert service.approve(db, first.id, _mgr(db)).status == "EXECUTED"


def _order(incoming):
    fc = Forecast(start=T, daily=[10.0] * 60, sigma_daily=3.0, level=10.0, weekday_index=[1.0] * 7)
    return compute_order(ReplenishmentInput(
        today=T, first_demand_day=T, lead_time_days=2, review_period_days=3, shelf_life_days=60, forecast=fc,
        lots=[LotState(10, T + timedelta(days=50))], incoming=incoming, z=1.28, unit_cost=7000, unit_price=10000)).qty


def test_overdue_po_still_counts_as_incoming():
    assert _order([Incoming(100, T - timedelta(days=1), T + timedelta(days=58))]) == 0 < _order([])


def test_cancel_po(client, manager, staff, db):
    po = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "SENT").order_by(PurchaseOrder.id)).first()
    url = f"/api/purchase-orders/{po.id}/cancel"
    assert client.post(url, json={"reason": "NCC hết hàng"}, headers=staff).status_code == 403
    assert client.post(url, json={"reason": "  "}, headers=manager).status_code == 422
    assert client.post(url, json={"reason": "NCC hết hàng"}, headers=manager).status_code == 200
    db.expire_all()
    assert db.get(PurchaseOrder, po.id).status == "CANCELLED"
    assert all(p.id != po.id for lines in on_order(db).values() for _, p in lines)
    assert client.post(url, json={"reason": "lần 2"}, headers=manager).status_code == 422
    body = {"lines": [{"line_id": l.id, "received_qty": l.qty, "expiry_date": "2027-01-01"} for l in po.lines]}
    assert client.post(f"/api/purchase-orders/{po.id}/receive", json=body, headers=staff).status_code == 422


def test_late_po_is_flagged(client, manager, db):
    po = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "SENT").order_by(PurchaseOrder.id)).first()
    original = po.expected_date
    po.expected_date = T - timedelta(days=2)
    db.commit()
    try:
        items = client.get("/api/briefing", headers=manager).json()["items"]
        assert any(i["id"] == "po_late" for i in items)
        rows = client.get("/api/purchase-orders?status=SENT&limit=300", headers=manager).json()
        assert next(r for r in rows if r["id"] == po.id)["overdue_days"] == 2
    finally:
        po.expected_date = original
        db.commit()


def test_receiving_without_expiry_is_refused(client, staff, db):
    po = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "SENT").order_by(PurchaseOrder.id)).first()
    body = {"lines": [{"line_id": l.id, "received_qty": l.qty, "expiry_date": None} for l in po.lines]}
    r = client.post(f"/api/purchase-orders/{po.id}/receive", json=body, headers=staff)
    assert r.status_code == 422 and "Thiếu hạn sử dụng" in r.text


def test_gross_profit_deducts_cost_of_returned_goods(db):
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    before = reports.cost_report(db, start, end)["kpi"]
    product = _first_product(db)
    row = StockMovement(product_id=product.id, date=date(2026, 10, 15), type="RETURN", qty=10, unit_cost=10000, value=70000)
    db.add(row)
    db.commit()
    try:
        after = reports.cost_report(db, start, end)["kpi"]
        assert after["gross_profit"] - before["gross_profit"] == -30000
        assert after["return_cost"] - before["return_cost"] == 100000
    finally:
        db.delete(row)
        db.commit()


def test_markdown_options_only_go_deeper():
    opts = evaluate(DispositionInput(qty=9, unit_cost=5, unit_price=10, days_left=2, expected_sold_full_price=6,
                                     elasticity=2.0, current_markdown=0.3))
    assert {o.markdown_pct for o in opts if o.action == "MARKDOWN"} == {0.5}
    assert next(o for o in opts if o.action == "KEEP").markdown_pct == 0.3


def test_keep_values_the_discount_already_applied():
    opts = evaluate(DispositionInput(qty=9, unit_cost=5, unit_price=10, days_left=2, expected_sold_full_price=6,
                                     elasticity=2.0, current_markdown=0.3))
    keep = next(o for o in opts if o.action == "KEEP")
    assert keep.units_sold == pytest.approx(9) and keep.value == pytest.approx(9 * 7)


def test_executor_never_raises_a_discounted_price(db, outbox):
    high = _only_lot(db, _first_product(db, freshness_class="SHORT"), 9, T + timedelta(days=2), markdown=0.5)
    low = _only_lot(db, _first_product(db, freshness_class="LONG"), 9, T + timedelta(days=2))
    payload = {"items": [{"lot_id": x.id, "sku": "X", "markdown_pct": 0.2} for x in (high, low)]}
    p = Proposal(type="MARKDOWN", status="PENDING", title="t", rationale="r", evidence={}, payload=payload,
                 original_payload=payload, created_by="job", created_at=datetime(2026, 11, 7))
    db.add(p)
    db.commit()
    done = service.approve(db, p.id, _mgr(db))
    db.refresh(high), db.refresh(low)
    assert done.status == "EXECUTED" and high.markdown_pct == 0.5 and low.markdown_pct == 0.2
    assert [k["lot_id"] for k in done.execution_result["kept_higher"]] == [high.id]


def test_evening_markdown_pays_for_evening_buyers_at_full_price():
    opts = evaluate(DispositionInput(qty=30, unit_cost=25000, unit_price=40000, days_left=0,
                                     expected_sold_full_price=10, elasticity=3.0, daily_demand=10))
    by_pct = {o.markdown_pct: o for o in opts if o.action == "MARKDOWN"}
    assert by_pct[0.5].delta_vs_keep == pytest.approx(92250 - 60000)
    assert opts[0].markdown_pct == 0.3  # truoc day chon 50% vi khong tinh phan nay


def test_return_value_unchanged_without_existing_discount():
    opts = evaluate(DispositionInput(qty=20, unit_cost=10000, unit_price=14000, days_left=10, expected_sold_full_price=5,
                                     elasticity=1.2, accepts_return=True, return_min_days_before_expiry=7, return_credit_pct=0.9))
    ret = next(o for o in opts if o.action == "RETURN")
    assert ret.value == pytest.approx(5 * 14000 + 15 * 10000 * 0.9)


@pytest.mark.parametrize("factor,ratio,expected", [
    (0.7, 0.8, "INCONCLUSIVE"),  # nhap it, het hang, ban it: khong chung minh nhu cau giam
    (0.7, 1.0, "WRONG"),         # het hang ma van ban bang du bao nen: chac chan khong giam
    (1.5, 1.05, "INCONCLUSIVE"),  # thieu hang nen ban khong tang duoc: khong chung minh gia thuyet sai
    (1.5, 1.4, "CORRECT"),       # het hang ma van tang: chac chan dung
])
def test_verdict_when_supply_limited(factor, ratio, expected):
    assert hypothesis_verdict(factor, ratio, supply_limited=True) == expected


def test_staff_cannot_revise_through_chat(db):
    _clear_open(db, "PURCHASE_ORDER")
    p, _, _ = builders.purchase_order(db, replenish.get_supplier(db, "NCC01"), "job")
    db.commit()
    line = p.payload["lines"][0]
    out = toolmod.REGISTRY["revise_proposal"].fn(toolmod.ToolContext(db=db, user=_staff(db)), proposal_id=p.id,
                                                 sku_qty=[{"sku": line["sku"], "qty": line["qty"] + 100}])
    db.refresh(p)
    assert "error" in out.data and p.status == "PENDING" and not out.ui


def _agreement(db, code):
    return db.scalar(select(Supplier).where(Supplier.code == code)).agreements[0]


def test_agreement_on_picks_the_one_in_force():
    s = Supplier(code="X", name="X", email="x", lead_time_days=1, order_weekdays=[0], min_order_value=0)
    old = SupplierAgreement(id=1, valid_from=date(2025, 1, 1), valid_to=date(2026, 12, 31), discount_pct=0.01)
    new = SupplierAgreement(id=2, valid_from=date(2026, 6, 1), valid_to=date(2027, 12, 31), discount_pct=0.05)
    s.agreements = [old, new]
    assert s.agreement_on(date(2026, 1, 1)) is old
    assert s.agreement_on(date(2026, 7, 1)) is new
    assert s.agreement_on(date(2028, 1, 1)) is None


def test_expired_agreement_gives_no_discount_and_warns(db):
    agr = _agreement(db, "NCC05")
    original = agr.valid_to
    agr.valid_to = T - timedelta(days=1)
    db.commit()
    try:
        s = replenish.get_supplier(db, "NCC05")
        db.refresh(s)
        out = replenish.suggest_po(db, s)
        assert any("hiệu lực" in w for w in out["warnings"])
        by_sku = {p.sku: p for p in db.scalars(select(Product).where(Product.supplier_id == s.id))}
        assert all(l["unit_cost"] == by_sku[l["sku"]].unit_cost for l in out["lines"])
    finally:
        agr.valid_to = original
        db.commit()


def test_return_refused_once_agreement_lapsed(db, outbox):
    _clear_open(db, "RETURN")
    lot = _at_risk_return_lot(db)
    (p, _), = builders.supplier_return(db, "job", lot_ids=[lot.id])
    db.commit()
    agr = _agreement(db, "NCC07")
    original = agr.valid_to
    agr.valid_to = T - timedelta(days=1)
    db.commit()
    try:
        done = service.approve(db, p.id, _mgr(db))
        assert done.status == "FAILED" and "hiệu lực" in done.execution_result["error"] and outbox == []
    finally:
        agr.valid_to = original
        db.commit()
