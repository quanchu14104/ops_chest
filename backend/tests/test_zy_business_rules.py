"""Quy tac nghiep vu: chong dat/tra trung, PO tre, KPI tra hang, hop dong het han, gio vang, cham gia thuyet."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

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


# ======================= Dot 1: so ton va an toan thuc pham =======================
from app.services import datecheck, shelf  # noqa: E402
from app.services.inventory import active_lots, expiring_lots  # noqa: E402
from app.services.receiving import ReceiveError, receive_po  # noqa: E402
from app.models import POLine  # noqa: E402


def _moves(db, proposal_id, typ=None):
    q = select(StockMovement).where(StockMovement.ref == f"proposal:{proposal_id}")
    if typ:
        q = q.where(StockMovement.type == typ)
    return db.scalars(q).all()


# ---- N3: bao huy kem ly do
def test_write_off_needs_approval_and_keeps_reason(db, outbox):
    lot = _only_lot(db, _first_product(db, freshness_class="SHORT"), 10, T + timedelta(days=5))
    p = builders.write_off(db, [{"lot_id": lot.id, "qty": 3, "reason": "DAMAGED"}], "user:nhanvien", "Rơi vỡ khi xếp kệ")
    db.commit()
    db.refresh(lot)
    assert p.status == "PENDING" and p.type == "DISPOSE" and lot.qty_remaining == 10
    assert service.approve(db, p.id, _mgr(db)).status == "EXECUTED"
    db.refresh(lot)
    (w,) = _moves(db, p.id, "WASTE")
    assert lot.qty_remaining == 7 and lot.status == "ACTIVE" and w.reason == "DAMAGED" and w.qty == 3
    rep = reports.cost_report(db, T, T)
    assert any(r["reason"] == "DAMAGED" and r["waste_qty"] >= 3 for r in rep["waste_by_reason"])


def test_write_off_rejects_expiry_reason_and_too_many_units(db):
    lot = _only_lot(db, _first_product(db, freshness_class="SHORT"), 4, T + timedelta(days=5))
    with pytest.raises(ValueError):
        builders.write_off(db, [{"lot_id": lot.id, "qty": 1, "reason": "EXPIRED"}], "user:nhanvien")
    with pytest.raises(ValueError):
        builders.write_off(db, [{"lot_id": lot.id, "qty": 5, "reason": "SPOILED"}], "user:nhanvien")


# ---- N2: rut ke ngay, duyet sau
def test_pulled_lot_leaves_stock_before_manager_approves(db, outbox):
    _clear_open(db, "DISPOSE")
    product = _first_product(db, freshness_class="FRESH")
    lot = _only_lot(db, product, 5, T)  # het ngay ban hom nay
    assert any(x["lot_id"] == lot.id for x in shelf.pull_list(db))
    assert "qty" not in shelf.pull_list(db)[0]  # dem mu
    shelf.confirm_pull(db, [{"lot_id": lot.id, "pulled_qty": 3}], "nhanvien")
    db.commit()
    db.refresh(lot)
    assert lot.status == "PULLED" and lot.qty_remaining == 5
    # Chua ai duyet ma lo da khong con la ton ban duoc / khong tinh vao don
    assert lot.id not in {l.id for ls in active_lots(db).values() for l in ls}
    sup = replenish.get_supplier(db, product.supplier.code)
    line = next((l for l in replenish.suggest_po(db, sup)["lines"] if l["sku"] == product.sku), None)
    assert line is None or line["on_hand"] == 0
    assert all(x["lot_id"] != lot.id for x in expiring_lots(db, days=3)["lots"])
    p, _ = builders.dispose_expired(db, "job")
    db.commit()
    it = next(i for i in p.payload["items"] if i["lot_id"] == lot.id)
    assert it["qty"] == 3 and it["book_qty"] == 5
    assert service.approve(db, p.id, _mgr(db)).status == "EXECUTED"
    db.refresh(lot)
    assert lot.status == "WASTED" and lot.qty_remaining == 0
    waste = [m for m in _moves(db, p.id, "WASTE") if m.lot_id == lot.id]
    adj = [m for m in _moves(db, p.id, "ADJUST") if m.lot_id == lot.id]
    assert [m.qty for m in waste] == [3] and [m.qty for m in adj] == [-2] and adj[0].reason == "SHRINK"


def test_cannot_pull_a_lot_still_on_sale(db):
    lot = _only_lot(db, _first_product(db, freshness_class="FRESH"), 5, T + timedelta(days=2))
    with pytest.raises(shelf.PullError):
        shelf.confirm_pull(db, [{"lot_id": lot.id, "pulled_qty": 5}], "nhanvien")
    db.rollback()


def test_last_sale_day_uses_pull_days(db):
    product = _first_product(db, freshness_class="LONG")
    assert product.pull_days_before_expiry == 7
    lot = _only_lot(db, product, 6, T + timedelta(days=3))  # con 3 ngay HSD nhung qua ngay ban cuoi
    assert lot.id in {x["lot_id"] for x in shelf.pull_list(db)}


def test_overdue_lot_edited_down_closes_instead_of_lingering(db, outbox):
    _clear_open(db, "DISPOSE")
    for l in db.scalars(select(Lot).where(Lot.status.in_(["ACTIVE", "PULLED"]), Lot.expiry_date < T + timedelta(days=10))):
        l.status = "SOLD"
    db.commit()
    lot = _only_lot(db, _first_product(db, freshness_class="FRESH"), 6, T - timedelta(days=1))
    p, _ = builders.dispose_expired(db, "job")
    db.commit()
    assert p.evidence["warnings"]  # chua ai xac nhan go ke
    done = service.approve(db, p.id, _mgr(db), edits={"items": [{"lot_id": lot.id, "qty": 4}]})
    assert done.status == "EXECUTED"
    db.refresh(lot)
    assert lot.status == "WASTED" and lot.qty_remaining == 0
    again, _ = builders.dispose_expired(db, "job")
    assert again is None or all(i["lot_id"] != lot.id for i in again.payload["items"])


# ---- N1: kiem date theo lo
def test_date_check_fixes_lots_and_surfaces_hidden_near_expiry(db, outbox):
    product = _first_product(db, freshness_class="SHORT")
    b = _only_lot(db, product, 10, T + timedelta(days=5))
    a = Lot(product_id=product.id, qty_received=10, qty_remaining=0, received_date=T - timedelta(days=5),
            expiry_date=T + timedelta(days=1), unit_cost=product.unit_cost, status="SOLD")
    db.add(a)
    db.commit()
    row = next(r for r in datecheck.sheet(db, "SHORT") if r["sku"] == product.sku)
    assert set(row) == {"sku", "name", "category", "freshness_class", "dates"}  # khong co so luong
    lines = [{"sku": product.sku, "expiry_date": a.expiry_date.isoformat(), "counted_qty": 3},
             {"sku": product.sku, "expiry_date": b.expiry_date.isoformat(), "counted_qty": 7}]
    shrink_before = reports.shrink_value(db, T, T)
    p, n = builders.date_check(db, lines, "user:nhanvien")
    db.commit()
    assert n == 1 and p.payload["mode"] == "LOT" and p.est_value == 0
    db.refresh(a), db.refresh(b)
    assert a.qty_remaining == 0 and b.qty_remaining == 10  # chua duyet thi so chua doi
    assert service.approve(db, p.id, _mgr(db)).status == "EXECUTED"
    db.refresh(a), db.refresh(b)
    assert (a.qty_remaining, a.status, b.qty_remaining) == (3, "ACTIVE", 7)
    assert sum(l.qty_remaining for l in active_lots(db, [product.id])[product.id]) == 10
    assert any(x["lot_id"] == a.id for x in expiring_lots(db, days=3)["lots"])
    assert reports.shrink_value(db, T, T) == shrink_before  # chuyen giua cac lo khong phai hao hut


def test_date_check_unlisted_book_date_counts_as_zero_and_new_date_creates_lot(db, outbox):
    product = _first_product(db, freshness_class="SHORT")
    old = _only_lot(db, product, 4, T + timedelta(days=2))
    new_exp = T + timedelta(days=6)
    p, _ = builders.date_check(db, [{"sku": product.sku, "expiry_date": new_exp.isoformat(), "counted_qty": 2}],
                               "user:nhanvien")
    db.commit()
    assert {(i["expiry_date"], i["diff"]) for i in p.payload["items"]} == {
        (old.expiry_date.isoformat(), -4), (new_exp.isoformat(), 2)}
    assert service.approve(db, p.id, _mgr(db)).status == "EXECUTED"
    lots = active_lots(db, [product.id])[product.id]
    assert [(l.expiry_date, l.qty_remaining) for l in lots] == [(new_exp, 2)]


def test_date_check_fails_if_lot_changed_after_count(db, outbox):
    product = _first_product(db, freshness_class="SHORT")
    lot = _only_lot(db, product, 9, T + timedelta(days=4))
    p, _ = builders.date_check(db, [{"sku": product.sku, "expiry_date": lot.expiry_date.isoformat(), "counted_qty": 5}],
                               "user:nhanvien")
    db.commit()
    lot.qty_remaining = 8
    db.commit()
    done = service.approve(db, p.id, _mgr(db))
    assert done.status == "FAILED" and "đếm lại" in done.execution_result["error"]


# ---- N4: nhan hang
def _new_po(db, product, qty, unit_cost=None):
    n = db.scalar(select(func.count()).select_from(PurchaseOrder)) + 1
    po = PurchaseOrder(code=f"PT{T:%y%m%d}-{n}", supplier_id=product.supplier_id, status="SENT",
                       order_date=T - timedelta(days=1), expected_date=T, total_value=qty * product.unit_cost)
    po.lines.append(POLine(product_id=product.id, qty=qty, unit_cost=unit_cost or product.unit_cost))
    db.add(po)
    db.commit()
    return po


def test_one_line_received_as_two_lots_with_two_expiries(db):
    product = _first_product(db, freshness_class="SHORT")
    po = _new_po(db, product, 24)
    e1, e2 = T + timedelta(days=6), T + timedelta(days=7)
    out = receive_po(db, po.id, [{"line_id": po.lines[0].id, "lots": [{"qty": 12, "expiry_date": e1.isoformat()},
                                                                      {"qty": 12, "expiry_date": e2.isoformat()}]}],
                     _staff(db))
    assert sorted((x["qty"], x["expiry_date"]) for x in out["lots"]) == [(12, e1.isoformat()), (12, e2.isoformat())]
    assert db.get(POLine, po.lines[0].id).received_qty == 24


def test_short_delivery_is_recorded_and_briefed(client, manager, db):
    product = _first_product(db, freshness_class="SHORT")
    po = _new_po(db, product, 24)
    out = receive_po(db, po.id, [{"line_id": po.lines[0].id, "received_qty": 18,
                                  "expiry_date": (T + timedelta(days=6)).isoformat()}], _staff(db))
    assert out["shortages"] == [{"sku": product.sku, "name": product.name, "ordered": 24, "short": 6}]
    db.expire_all()
    assert db.get(POLine, po.lines[0].id).short_qty == 6
    items = client.get("/api/briefing", headers=manager).json()["items"]
    assert any(i["id"] == f"short-{po.code}" for i in items)


def test_short_dated_lot_blocked_for_staff_allowed_with_manager(db):
    product = _first_product(db, freshness_class="SHORT")  # 7 ngay -> chuan nhan 5 ngay
    exp = (T + timedelta(days=2)).isoformat()
    po = _new_po(db, product, 8)
    line = {"line_id": po.lines[0].id, "received_qty": 8, "expiry_date": exp, "accept_short_dated": True}
    with pytest.raises(ReceiveError, match="chuẩn nhận hàng"):
        receive_po(db, po.id, [line], _staff(db))  # nhan vien tick cung khong duoc
    db.rollback()
    out = receive_po(db, po.id, [line], _mgr(db))
    assert out["lots"] and any("date ngắn" in w for w in out["warnings"])


def test_short_dated_units_can_be_refused_at_the_door(db):
    product = _first_product(db, freshness_class="SHORT")
    po = _new_po(db, product, 8)
    out = receive_po(db, po.id, [{"line_id": po.lines[0].id,
                                  "lots": [{"qty": 5, "expiry_date": (T + timedelta(days=6)).isoformat()}],
                                  "rejected_qty": 3, "reject_reason": "SHORT_DATED"}], _staff(db))
    pl = db.get(POLine, po.lines[0].id)
    assert out["lots"][0]["qty"] == 5 and pl.rejected_qty == 3 and pl.short_qty is None


def test_over_delivery_needs_manager(db):
    product = _first_product(db, freshness_class="SHORT")
    po = _new_po(db, product, 10)
    line = {"line_id": po.lines[0].id, "received_qty": 10 + max(1, product.pack_size) + 1,
            "expiry_date": (T + timedelta(days=6)).isoformat(), "accept_over": True}
    with pytest.raises(ReceiveError, match="dư"):
        receive_po(db, po.id, [line], _staff(db))
    db.rollback()
    assert receive_po(db, po.id, [line], _mgr(db))["lots"]


def test_invoice_cost_used_for_lot_and_flagged(db):
    product = _first_product(db, freshness_class="SHORT")
    po = _new_po(db, product, 4)
    out = receive_po(db, po.id, [{"line_id": po.lines[0].id, "received_qty": 4,
                                  "actual_unit_cost": product.unit_cost + 500,
                                  "expiry_date": (T + timedelta(days=6)).isoformat()}], _staff(db))
    lot = db.get(Lot, out["lots"][0]["lot_id"])
    assert lot.unit_cost == product.unit_cost + 500 and any("hóa đơn" in w for w in out["warnings"])


# ======================= Dot 2: dat hang =======================
from app.engines.replenishment import schedule, service_floor  # noqa: E402
from app.models import SupplierClosure  # noqa: E402


def _engine_order(**kw):
    fc = Forecast(start=T, daily=[10.0] * 60, sigma_daily=4.0, level=10.0, weekday_index=[1.0] * 7)
    base = dict(today=T, first_demand_day=T, lead_time_days=1, review_period_days=1, shelf_life_days=2, forecast=fc,
                lots=[], unit_cost=9000, unit_price=10000, salvage_per_unit=0)
    base.update(kw)
    return compute_order(ReplenishmentInput(**base))


# ---- N6: san muc phuc vu
def test_newsvendor_never_plans_below_service_floor():
    low = _engine_order()  # lai mong, khong thu hoi: newsvendor tu chon muc phuc vu rat thap
    floored = _engine_order(min_service_level=0.95)
    assert low.service_level < 0.5
    assert floored.service_level == pytest.approx(0.95) and floored.qty > low.qty


def test_order_up_to_z_raised_to_floor():
    res = _engine_order(shelf_life_days=180, z=0.84, min_service_level=0.90)
    assert res.mode == "order_up_to" and res.service_level == pytest.approx(0.90, abs=1e-3)


def test_floor_by_role():
    assert service_floor(True, "C") == 0.95 and service_floor(False, "A") == 0.90 and service_floor(False, "B") == 0.50


def test_po_lines_carry_service_floor(db):
    sug = replenish.suggest_po(db, replenish.get_supplier(db, "NCC01"))
    traffic = {p.sku for p in db.scalars(select(Product).where(Product.is_traffic_driver.is_(True)))}
    lines = [l for l in sug["lines"] if l["sku"] in traffic]
    assert lines and all(l["explain"]["service_level"] >= 0.95 - 1e-6 for l in lines)


# ---- N9: suc chua va ton trung bay
def test_capacity_caps_order_and_is_flagged():
    free = _engine_order(shelf_life_days=180, z=1.65)
    # 15 tren ke, hom nay ban 10 -> luc hang ve con 5; suc chua 12 -> chi con cho cho 7
    capped = _engine_order(shelf_life_days=180, z=1.65, pack_size=6, max_stock=12, lots=[LotState(15, T + timedelta(days=100))])
    assert free.qty > 7
    assert capped.capped_by_capacity and capped.qty == 6


def test_min_display_sets_safety_floor_for_durables():
    fc = Forecast(start=T, daily=[0.2] * 60, sigma_daily=0.1, level=0.2, weekday_index=[1.0] * 7)
    res = _engine_order(shelf_life_days=180, z=1.0, forecast=fc, min_display=6)
    assert res.safety_stock >= 6 and res.qty >= 6


def test_suggest_po_respects_capacity(db):
    sup = replenish.get_supplier(db, "NCC08")  # kem: tu dong co suc chua
    for l in replenish.suggest_po(db, sup)["lines"]:
        p = db.get(Product, l["product_id"])
        assert p.max_stock_qty and l["explain"]["projected_usable_at_arrival"] + l["qty"] <= p.max_stock_qty


# ---- N7: lich giao va lich nghi
def test_last_order_before_closure_covers_the_break():
    mon = date(2026, 11, 9)
    closed = lambda d: date(2026, 11, 12) <= d <= date(2026, 11, 20)  # noqa: E731
    arrival, R = schedule(mon, 2, [0, 3], [1, 2, 4, 5], closed)
    assert arrival == date(2026, 11, 11) and R == (date(2026, 11, 25) - arrival).days
    assert schedule(mon, 2, [0, 3], [1, 2, 4, 5]) == (arrival, 3)


def test_supplier_closure_enlarges_order_and_warns(db):
    sup = replenish.get_supplier(db, "NCC05")
    mon = date(2026, 11, 9)
    normal = replenish.suggest_po(db, sup, order_date=mon)
    row = SupplierClosure(supplier_id=sup.id, start_date=date(2026, 11, 12), end_date=date(2026, 11, 20), reason="Thử")
    db.add(row)
    db.commit()
    try:
        db.refresh(sup)
        holiday = replenish.suggest_po(db, sup, order_date=mon)
        assert holiday["review_period_days"] > normal["review_period_days"]
        assert holiday["total_value"] > normal["total_value"]
        assert any("nghỉ từ 12/11/2026" in w and "đơn cuối" in w for w in holiday["warnings"])
        clock.set_today(date(2026, 11, 13))
        assert sup not in replenish.suppliers_due(db)  # dang nghi: khong den lich dat
    finally:
        db.delete(row)
        db.commit()


# ---- N8: don duoi gia tri toi thieu
def test_below_minimum_requires_ack(db, outbox):
    _clear_open(db, "PURCHASE_ORDER")
    sup = replenish.get_supplier(db, "NCC01")  # hang tuoi, ngay nao cung can dat
    original = sup.min_order_value
    sup.min_order_value = 10 ** 10
    db.commit()
    try:
        p, created, _ = builders.purchase_order(db, sup, "job")
        db.commit()
        mo = p.payload["min_order"]
        assert created and mo["shortfall"] > 0 and "feasible" in mo["defer"] and "lines" in mo["top_up"]
        done = service.approve(db, p.id, _mgr(db))
        assert done.status == "FAILED" and "tối thiểu" in done.execution_result["error"] and outbox == []
        done = service.approve(db, p.id, _mgr(db), edits={"min_order_ack": True})
        assert done.status == "EXECUTED" and len(outbox) == 1
    finally:
        sup.min_order_value = original
        db.commit()


def test_top_up_pulls_forward_lowest_cover_within_room():
    pool = [{"product_id": 1, "sku": "A1", "name": "a", "pack_size": 6, "unit_cost": 1000, "daily": 2.0, "position": 4, "room": 12},
            {"product_id": 2, "sku": "B1", "name": "b", "pack_size": 12, "unit_cost": 1000, "daily": 1.0, "position": 30, "room": 100}]
    mo = replenish.min_order_options(40_000, 10_000, pool, [])
    added = {l["sku"]: l["add_qty"] for l in mo["top_up"]["lines"]}
    assert added["A1"] == 12  # it ngay ton nhat duoc keo truoc, dung toi da cho trong (room)
    assert mo["top_up"]["reaches_min"] and mo["top_up"]["added_value"] >= 30_000
    assert mo["defer"]["feasible"] is True


# ---- N15: dong SM tu them cung duoc chiet khau
def test_line_added_by_manager_gets_agreement_discount(db):
    sup = replenish.get_supplier(db, "NCC05")
    payload = {"supplier_id": sup.id, "lines": [], "total_value": 0, "note": ""}
    p = Proposal(type="PURCHASE_ORDER", status="PENDING", title="t", rationale="r", evidence={}, payload=payload,
                 original_payload=payload, created_by="job", created_at=datetime(2026, 11, 7))
    extra = db.scalars(select(Product).where(Product.supplier_id == sup.id).order_by(Product.sku)).first()
    service.apply_edits(db, p, {"lines": [{"product_id": extra.id, "qty": 24}]}, _mgr(db))
    line = next(l for l in p.payload["lines"] if l["product_id"] == extra.id)
    disc = sup.agreement_on(T).discount_pct
    assert disc > 0 and line["unit_cost"] == int(round(extra.unit_cost * (1 - disc)))
    db.rollback()
