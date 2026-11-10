"""Tinh de xuat don dat hang (PO) cho mot nha cung cap tu du lieu DB + engine replenishment."""
from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.fmt import vnd
from app.clock import today
from app.engines.abc_xyz import Z_BY_CLASS
from app.config import service_floors
from app.engines.replenishment import Incoming, LotState, ReplenishmentInput, compute_order, service_floor
from app.models import Product, Supplier
from app.services.history import abc_xyz_classes, forecast_for
from app.services.inventory import active_lots, on_order
from app.services.learning import active_adjustments

WEEKDAY_NAMES = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def salvage_value(p: Product, agr) -> float:
    v = 0.2 * p.unit_price if p.freshness_class in ("FRESH", "SHORT") else 0.0
    if agr and agr.accepts_near_expiry_return:
        v = max(v, 0.5 * p.unit_cost * agr.return_credit_pct)
    return v


def stockout_penalty(p: Product) -> float:
    return p.unit_price * (1.0 if p.is_traffic_driver else 0.3)


def suppliers_due(db: Session, d: date | None = None) -> list[Supplier]:
    """NCC den lich dat hom nay (bo qua NCC dang nghi: don se khong duoc giao)."""
    d = d or today()
    return [s for s in db.scalars(select(Supplier).order_by(Supplier.code))
            if d.weekday() in s.order_weekdays and not s.is_closed(d)]


def apply_order_adjustment(qty: int, factor: float, pack_size: int, shelf_life_cap: float) -> int:
    """He so SM da duyet. Tang thi van khong vuot tran HSD; lam tron theo quy cach dong goi."""
    pack = max(1, pack_size)
    target = qty * factor
    if factor > 1:  # lam tron xuong de khong vuot tran HSD; qty da la boi so cua thung nen khong tut duoi qty
        return max(qty, math.floor(min(target, shelf_life_cap) / pack + 1e-9) * pack)
    return max(1, int(round(target / pack))) * pack  # van can dat thi giu it nhat mot thung


def suggest_po(db: Session, supplier: Supplier, order_date: date | None = None) -> dict:
    """Dat buoi sang truoc gio ban: nhu cau hom nay van phai tru vao ton hien co."""
    t = order_date or today()
    agr = supplier.agreement_on(t)
    L = supplier.lead_time_days
    arrival, R = supplier.schedule(t)
    lead = (arrival - t).days
    products = db.scalars(
        select(Product).where(Product.supplier_id == supplier.id, Product.status == "ACTIVE").order_by(Product.sku)
    ).all()
    lots = active_lots(db, [p.id for p in products])
    incoming = on_order(db)
    classes = abc_xyz_classes(db)
    discount = agr.discount_pct if agr else 0.0
    adjustments = active_adjustments(db)
    floors = service_floors()
    lines, results, topup_pool = [], {}, []
    for p in products:
        pull = p.pull_days_before_expiry or 0
        life = max(1, p.shelf_life_days - pull)  # so ngay ban duoc cua lo moi
        fc = forecast_for(db, p, horizon=lead + R + min(life, 30) + 2, start=t)
        cell = classes[p.sku].cell if p.sku in classes else "BY"
        res = compute_order(ReplenishmentInput(
            today=t, first_demand_day=t, lead_time_days=L, review_period_days=R, arrival_date=arrival,
            shelf_life_days=life, forecast=fc,
            lots=[LotState(l.qty_remaining, l.sell_by) for l in lots.get(p.id, []) if l.sell_by >= t],
            incoming=[Incoming(q, po.expected_date, po.expected_date + timedelta(days=life - 1))
                      for q, po in incoming.get(p.id, [])],
            pack_size=p.pack_size, z=Z_BY_CLASS.get(cell, 1.28), unit_cost=p.unit_cost, unit_price=p.unit_price,
            salvage_per_unit=salvage_value(p, agr), stockout_penalty_per_unit=stockout_penalty(p),
            min_service_level=service_floor(p.is_traffic_driver, cell[0], floors),
            max_stock=p.max_stock_qty, min_display=p.min_display_qty or 0,
        ))
        adj = adjustments.get(p.category)
        qty = apply_order_adjustment(res.qty, adj.factor, p.pack_size, res.shelf_life_cap) if adj and res.qty > 0 else res.qty
        if res.capacity_cap is not None:  # he so hoc tu SM cung khong vuot suc chua
            qty = min(qty, int(res.capacity_cap // max(1, p.pack_size)) * max(1, p.pack_size))
        unit_cost = int(round(p.unit_cost * (1 - discount)))
        results[p.id] = res
        if p.freshness_class == "LONG" and cell[0] in "AB":  # ung vien keo som de bu don toi thieu
            daily = res.demand_coverage / max(1, R)
            room = res.shelf_life_cap - qty
            if res.capacity_cap is not None:
                room = min(room, res.capacity_cap - qty)
            if daily > 0 and room >= p.pack_size:
                topup_pool.append({"product_id": p.id, "sku": p.sku, "name": p.name, "pack_size": max(1, p.pack_size),
                                   "unit_cost": unit_cost, "daily": daily, "position": res.projected_usable_at_arrival + qty,
                                   "room": room, "in_order": qty > 0})
        if qty <= 0:
            continue
        lines.append({
            "product_id": p.id, "sku": p.sku, "name": p.name, "qty": qty, "suggested_qty": qty,
            "pack_size": p.pack_size, "unit_cost": unit_cost, "line_value": qty * unit_cost,
            "abc_xyz": cell, "freshness_class": p.freshness_class,
            "on_hand": sum(l.qty_remaining for l in lots.get(p.id, [])),
            "forecast_cover": round(res.demand_coverage, 1),
            "explain": {**res.to_dict(), "hypotheses": fc.adjustments,
                        "order_adjustment": adj.factor if adj else None, "qty_before_adjustment": res.qty},
        })
    total = sum(l["line_value"] for l in lines)
    warnings = []
    if agr is None and supplier.agreements:
        warnings.append("Thỏa thuận với NCC không có hiệu lực vào ngày đặt: đơn này chưa áp chiết khấu, cần gia hạn.")
    min_order = None
    if lines and supplier.min_order_value and total < supplier.min_order_value:
        min_order = min_order_options(supplier.min_order_value, total, topup_pool,
                                      [(l["sku"], results[l["product_id"]]) for l in lines])
        warnings.append(
            f"Tổng đơn {vnd(total)} thấp hơn giá trị đơn tối thiểu {vnd(supplier.min_order_value)} của NCC. "
            "Chọn bù đơn bằng hàng bền, hoãn sang lần đặt sau, hoặc xác nhận đã thỏa thuận với NCC trước khi duyệt."
        )
    if t.weekday() not in supplier.order_weekdays:
        days = ", ".join(WEEKDAY_NAMES[i] for i in supplier.order_weekdays)
        warnings.append(f"Hôm nay không phải ngày đặt hàng thường lệ của NCC (lịch: {days}).")
    nxt = upcoming_closure(supplier, t)
    if nxt:
        warnings.append(closure_text(supplier, nxt))
    capacity = [l["sku"] for l in lines if l["explain"]["capped_by_capacity"]]
    if capacity:
        warnings.append(f"{len(capacity)} mặt hàng bị chặn theo sức chứa kệ/tủ: {', '.join(capacity[:5])}.")
    return {
        "supplier_id": supplier.id, "supplier_code": supplier.code, "supplier_name": supplier.name,
        "supplier_email": supplier.email, "order_date": t.isoformat(),
        "expected_date": arrival.isoformat(), "review_period_days": R, "lead_time_days": L,
        "lines": lines, "total_value": total, "min_order_value": supplier.min_order_value, "warnings": warnings,
        "min_order": min_order,
    }


def min_order_options(min_value: int, total: int, pool: list[dict], line_results: list[tuple]) -> dict:
    """Hai phuong an khi don duoi gia tri toi thieu, de SM chon:
    - Bu don: keo som hang ben nhom A/B co so ngay ton thap nhat, tung thung mot, khong vuot tran HSD/suc chua.
    - Hoan: chi kha thi neu khong SKU nao trong don het hang truoc lan giao ke tiep (theo du bao, chua tinh ton an toan).
    """
    added: dict[int, int] = {}
    value = total
    pool = [dict(c) for c in pool]
    for _ in range(1000):
        if value >= min_value:
            break
        open_ = [c for c in pool if c["room"] - added.get(c["product_id"], 0) >= c["pack_size"]]
        if not open_:
            break
        c = min(open_, key=lambda c: (c["position"] + added.get(c["product_id"], 0)) / c["daily"])
        added[c["product_id"]] = added.get(c["product_id"], 0) + c["pack_size"]
        value += c["pack_size"] * c["unit_cost"]
    by_id = {c["product_id"]: c for c in pool}
    top_lines = [{"product_id": pid, "sku": by_id[pid]["sku"], "name": by_id[pid]["name"], "add_qty": q,
                  "unit_cost": by_id[pid]["unit_cost"], "line_value": q * by_id[pid]["unit_cost"],
                  "days_cover_before": round(by_id[pid]["position"] / by_id[pid]["daily"], 1)}
                 for pid, q in added.items()]
    at_risk = [sku for sku, r in line_results if r.demand_coverage - r.served_by_existing >= 0.5]
    return {
        "shortfall": min_value - total,
        "top_up": {"lines": top_lines, "added_value": value - total, "reaches_min": value >= min_value},
        "defer": {"feasible": not at_risk, "at_risk": at_risk},
    }


def upcoming_closure(supplier: Supplier, t: date, within_days: int = 21):
    return next((c for c in supplier.closures if c.end_date >= t and c.start_date <= t + timedelta(days=within_days)), None)


def last_order_day_before(supplier: Supplier, closure) -> date | None:
    d = closure.start_date - timedelta(days=1)
    for _ in range(14):
        if d.weekday() in supplier.order_weekdays and not supplier.is_closed(d):
            return d
        d -= timedelta(days=1)
    return None


def closure_text(supplier: Supplier, c) -> str:
    last = last_order_day_before(supplier, c)
    tail = f", đơn cuối trước kỳ nghỉ là ngày {last:%d/%m/%Y}" if last else ""
    why = f" ({c.reason})" if c.reason else ""
    return (f"{supplier.name} nghỉ từ {c.start_date:%d/%m/%Y} đến {c.end_date:%d/%m/%Y}{why}{tail}. "
            "Đơn trước kỳ nghỉ đã được tính để phủ cả kỳ nghỉ (vẫn chặn theo HSD).")


def get_supplier(db: Session, code_or_id: str | int) -> Supplier | None:
    q = select(Supplier).options(joinedload(Supplier.agreements))
    if isinstance(code_or_id, int) or str(code_or_id).isdigit():
        return db.scalar(q.where(Supplier.id == int(code_or_id)))
    s = str(code_or_id)
    return db.scalar(q.where(Supplier.code == s.upper())) or db.scalar(q.where(Supplier.name.ilike(f"%{s}%")))
