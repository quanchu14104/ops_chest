"""Tinh de xuat don dat hang (PO) cho mot nha cung cap tu du lieu DB + engine replenishment."""
from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.fmt import vnd
from app.clock import today
from app.engines.abc_xyz import Z_BY_CLASS
from app.engines.replenishment import Incoming, LotState, ReplenishmentInput, compute_order, review_period
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
    d = d or today()
    return [s for s in db.scalars(select(Supplier).order_by(Supplier.code)) if d.weekday() in s.order_weekdays]


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
    R = review_period(supplier.order_weekdays, t)
    products = db.scalars(
        select(Product).where(Product.supplier_id == supplier.id, Product.status == "ACTIVE").order_by(Product.sku)
    ).all()
    lots = active_lots(db, [p.id for p in products])
    incoming = on_order(db)
    classes = abc_xyz_classes(db)
    discount = agr.discount_pct if agr else 0.0
    adjustments = active_adjustments(db)
    lines = []
    for p in products:
        fc = forecast_for(db, p, horizon=L + R + min(p.shelf_life_days, 30) + 2, start=t)
        cell = classes[p.sku].cell if p.sku in classes else "BY"
        res = compute_order(ReplenishmentInput(
            today=t, first_demand_day=t, lead_time_days=L, review_period_days=R,
            shelf_life_days=p.shelf_life_days, forecast=fc,
            lots=[LotState(l.qty_remaining, l.expiry_date) for l in lots.get(p.id, []) if l.expiry_date >= t],
            incoming=[Incoming(q, po.expected_date, po.expected_date + timedelta(days=p.shelf_life_days - 1))
                      for q, po in incoming.get(p.id, [])],
            pack_size=p.pack_size, z=Z_BY_CLASS.get(cell, 1.28), unit_cost=p.unit_cost, unit_price=p.unit_price,
            salvage_per_unit=salvage_value(p, agr), stockout_penalty_per_unit=stockout_penalty(p),
        ))
        adj = adjustments.get(p.category)
        qty = apply_order_adjustment(res.qty, adj.factor, p.pack_size, res.shelf_life_cap) if adj and res.qty > 0 else res.qty
        if qty <= 0:
            continue
        unit_cost = int(round(p.unit_cost * (1 - discount)))
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
    if lines and supplier.min_order_value and total < supplier.min_order_value:
        warnings.append(
            f"Tổng đơn {vnd(total)} thấp hơn giá trị đơn tối thiểu {vnd(supplier.min_order_value)} của NCC. "
            "Có thể gộp vào lần đặt sau hoặc thương lượng phí giao."
        )
    if t.weekday() not in supplier.order_weekdays:
        days = ", ".join(WEEKDAY_NAMES[i] for i in supplier.order_weekdays)
        warnings.append(f"Hôm nay không phải ngày đặt hàng thường lệ của NCC (lịch: {days}).")
    return {
        "supplier_id": supplier.id, "supplier_code": supplier.code, "supplier_name": supplier.name,
        "supplier_email": supplier.email, "order_date": t.isoformat(),
        "expected_date": (t + timedelta(days=L)).isoformat(), "review_period_days": R, "lead_time_days": L,
        "lines": lines, "total_value": total, "min_order_value": supplier.min_order_value, "warnings": warnings,
    }


def get_supplier(db: Session, code_or_id: str | int) -> Supplier | None:
    q = select(Supplier).options(joinedload(Supplier.agreements))
    if isinstance(code_or_id, int) or str(code_or_id).isdigit():
        return db.scalar(q.where(Supplier.id == int(code_or_id)))
    s = str(code_or_id)
    return db.scalar(q.where(Supplier.code == s.upper())) or db.scalar(q.where(Supplier.name.ilike(f"%{s}%")))
