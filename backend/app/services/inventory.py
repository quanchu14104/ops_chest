from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.clock import today
from app.engines.abc_xyz import POLICY_BY_CLASS
from app.engines.disposition import ELASTICITY, DispositionInput, evaluate
from app.engines.expiry import LotInput, bucket, project_lots
from app.models import Lot, POLine, Product, Proposal, PurchaseOrder, Supplier
from app.services.history import abc_xyz_classes, forecast_for, load_history


def active_lots(db: Session, product_ids: list[int] | None = None) -> dict[int, list[Lot]]:
    q = select(Lot).where(Lot.status == "ACTIVE", Lot.qty_remaining > 0)
    if product_ids is not None:
        q = q.where(Lot.product_id.in_(product_ids))
    out: dict[int, list[Lot]] = defaultdict(list)
    for lot in db.scalars(q.order_by(Lot.expiry_date, Lot.id)):
        out[lot.product_id].append(lot)
    return out


def on_order(db: Session) -> dict[int, list[tuple[int, PurchaseOrder]]]:
    rows = db.execute(
        select(POLine, PurchaseOrder).join(PurchaseOrder, POLine.po_id == PurchaseOrder.id)
        .where(PurchaseOrder.status == "SENT")
    ).all()
    out: dict[int, list] = defaultdict(list)
    for line, po in rows:
        out[line.product_id].append((line.qty, po))
    return out


def find_products(db: Session, query: str | None = None, category: str | None = None, limit: int = 20) -> list[Product]:
    q = select(Product).options(joinedload(Product.supplier))
    if query:
        like = f"%{query}%"
        q = q.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category:
        q = q.where(Product.category.ilike(f"%{category}%"))
    return list(db.scalars(q.order_by(Product.sku).limit(limit)))


def inventory_summary(db: Session) -> dict:
    t = today()
    products = db.scalars(select(Product)).all()
    lots = active_lots(db)
    by_cat: dict[str, dict] = defaultdict(lambda: {"skus": 0, "units": 0, "value": 0, "out_of_stock": 0})
    expiring_3d_value = 0
    expired_value = 0
    for p in products:
        c = by_cat[p.category]
        c["skus"] += 1
        units = sum(l.qty_remaining for l in lots.get(p.id, []))
        c["units"] += units
        c["value"] += sum(l.qty_remaining * l.unit_cost for l in lots.get(p.id, []))
        if units == 0 and p.status == "ACTIVE":
            c["out_of_stock"] += 1
        for l in lots.get(p.id, []):
            dl = (l.expiry_date - t).days
            if dl < 0:
                expired_value += l.qty_remaining * l.unit_cost
            elif dl <= 3:
                expiring_3d_value += l.qty_remaining * l.unit_cost
    pending = db.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "PENDING"))
    incoming = db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "SENT"))
    return {
        "as_of": t.isoformat(),
        "total_skus": len(products),
        "active_skus": sum(1 for p in products if p.status == "ACTIVE"),
        "total_units": sum(c["units"] for c in by_cat.values()),
        "total_value": sum(c["value"] for c in by_cat.values()),
        "out_of_stock_skus": sum(c["out_of_stock"] for c in by_cat.values()),
        "value_expiring_within_3_days": expiring_3d_value,
        "value_already_expired_on_shelf": expired_value,
        "pending_proposals": pending,
        "purchase_orders_awaiting_delivery": incoming,
        "by_category": [{"category": k, **v} for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1]["value"])],
    }


def expiring_lots(db: Session, days: int = 7, category: str | None = None, with_options: bool = True) -> dict:
    """Lo con han <= `days` ngay (va lo da qua han con tren ke), kem du kien huy va phuong an xu ly."""
    t = today()
    q = (select(Lot).options(joinedload(Lot.product).joinedload(Product.supplier).joinedload(Supplier.agreements))
         .where(Lot.status == "ACTIVE", Lot.qty_remaining > 0, Lot.expiry_date <= t + timedelta(days=days)))
    if category:
        q = q.join(Product).where(Product.category.ilike(f"%{category}%"))
    near = db.scalars(q).unique().all()
    pids = sorted({l.product_id for l in near})
    all_lots = active_lots(db, pids)
    items = []
    for pid in pids:
        p = all_lots[pid][0].product if all_lots[pid] else next(l.product for l in near if l.product_id == pid)
        lots = all_lots[pid]
        max_exp = max(l.expiry_date for l in lots)
        horizon = max(1, min(120, (max_exp - t).days + 1))
        fc = forecast_for(db, p, horizon=horizon, start=t)
        risks = {r.lot_id: r for r in project_lots(
            [LotInput(l.id, l.qty_remaining, l.expiry_date) for l in lots if l.expiry_date >= t], fc.daily, t)}
        agr = p.supplier.agreements[0] if p.supplier.agreements else None
        for l in lots:
            if l.expiry_date > t + timedelta(days=days):
                continue
            dl = (l.expiry_date - t).days
            if dl < 0:
                item = dict(expected_sold=0, expected_waste=l.qty_remaining, status="EXPIRED")
                options = []
            else:
                r = risks[l.id]
                item = dict(expected_sold=r.expected_sold, expected_waste=r.expected_waste, status="AT_RISK"
                            if r.expected_waste >= 1 else "OK")
                options = []
                if with_options and r.expected_waste >= 1:
                    options = [o.to_dict() for o in evaluate(DispositionInput(
                        qty=l.qty_remaining, unit_cost=l.unit_cost, unit_price=p.unit_price, days_left=dl,
                        expected_sold_full_price=r.expected_sold, elasticity=ELASTICITY[p.freshness_class],
                        accepts_return=bool(agr and agr.accepts_near_expiry_return),
                        return_min_days_before_expiry=agr.return_min_days_before_expiry if agr else 0,
                        return_credit_pct=agr.return_credit_pct if agr else 0.0, daily_demand=fc.daily[0],
                    ))][:3]
            items.append({
                "lot_id": l.id, "product_id": p.id, "sku": p.sku, "name": p.name, "category": p.category,
                "freshness_class": p.freshness_class, "qty": l.qty_remaining, "expiry_date": l.expiry_date.isoformat(),
                "days_left": dl, "bucket": "Đã quá hạn" if dl < 0 else bucket(dl), "unit_cost": l.unit_cost,
                "unit_price": p.unit_price, "markdown_pct": l.markdown_pct,
                "value_at_risk": int(round(item["expected_waste"] * l.unit_cost)),
                "supplier": p.supplier.name, **item, "options": options,
            })
    items.sort(key=lambda x: (x["days_left"], -x["value_at_risk"]))
    by_bucket: dict[str, dict] = defaultdict(lambda: {"lots": 0, "value_at_risk": 0})
    for it in items:
        b = by_bucket[it["bucket"]]
        b["lots"] += 1
        b["value_at_risk"] += it["value_at_risk"]
    return {"as_of": t.isoformat(), "days": days, "lots": items,
            "summary": [{"bucket": k, **v} for k, v in by_bucket.items()],
            "total_value_at_risk": sum(i["value_at_risk"] for i in items)}


def product_detail(db: Session, sku: str) -> dict | None:
    p = db.scalar(select(Product).options(joinedload(Product.supplier)).where(Product.sku == sku))
    if not p:
        return None
    t = today()
    h = load_history(db)
    lots = active_lots(db, [p.id]).get(p.id, [])
    fc = forecast_for(db, p, horizon=14, start=t)
    cls = abc_xyz_classes(db).get(p.sku)
    incoming = on_order(db).get(p.id, [])
    sales28 = h.series(p.id, "sales", 28)
    return {
        "sku": p.sku, "name": p.name, "category": p.category, "status": p.status,
        "freshness_class": p.freshness_class, "shelf_life_days": p.shelf_life_days,
        "unit_cost": p.unit_cost, "unit_price": p.unit_price, "pack_size": p.pack_size,
        "is_traffic_driver": p.is_traffic_driver, "substitutes": p.substitute_skus,
        "supplier": {"code": p.supplier.code, "name": p.supplier.name, "lead_time_days": p.supplier.lead_time_days,
                     "order_weekdays": p.supplier.order_weekdays},
        "on_hand": sum(l.qty_remaining for l in lots),
        "lots": [{"lot_id": l.id, "qty": l.qty_remaining, "received": l.received_date.isoformat(),
                  "expiry_date": l.expiry_date.isoformat(), "days_left": (l.expiry_date - t).days,
                  "markdown_pct": l.markdown_pct} for l in lots],
        "incoming": [{"po": po.code, "qty": q, "expected_date": po.expected_date.isoformat()} for q, po in incoming],
        "sales_last_28d": {"total": sum(sales28), "avg_per_day": round(sum(sales28) / 28, 2),
                           "stockout_days": sum(h.series(p.id, "stockout", 28))},
        "forecast_next_14d": {"daily": [round(x, 1) for x in fc.daily], "total": round(sum(fc.daily), 1),
                              "weekday_index": fc.weekday_index, "sigma_daily": round(fc.sigma_daily, 2),
                              "censored_days_adjusted": fc.n_censored},
        "abc_xyz": None if not cls else {"cell": cls.cell, "cv": cls.cv, "margin_90d": round(cls.margin),
                                         "policy": POLICY_BY_CLASS[cls.cell]},
    }
