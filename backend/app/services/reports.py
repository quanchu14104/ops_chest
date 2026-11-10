"""Bao cao: nhap/xuat kho, chi phi, KPI, ABC-XYZ. Moi so lieu kem khoang thoi gian."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import today
from app.engines.abc_xyz import POLICY_BY_CLASS, delist_candidates
from app.engines.kpi import KpiTotals, summarize
from app.models import DailySales, Lot, Product, StockMovement
from app.models.inventory import WASTE_REASONS
from app.services import snapshots
from app.services.history import abc_xyz_classes, daily_totals, sku_stats


def default_range(start: date | None, end: date | None, days: int = 30) -> tuple[date, date]:
    end = end or today() - timedelta(days=1)
    start = start or end - timedelta(days=days - 1)
    return start, end


def _bucket_key(d: date, group: str) -> str:
    if group == "week":
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat()
    if group == "month":
        return d.strftime("%Y-%m")
    return d.isoformat()


def stock_flow(db: Session, start: date, end: date, group: str = "day", category: str | None = None,
               sku: str | None = None) -> list[dict]:
    """Hang vao (nhap) va ra (ban, huy, tra NCC) theo ngay/tuan/thang. Don vi: so luong va gia von."""
    pq = select(Product.id)
    if category:
        pq = pq.where(Product.category.ilike(f"%{category}%"))
    if sku:
        pq = pq.where(Product.sku == sku.upper())
    pids = list(db.scalars(pq))
    rows: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for d, q, cogs in db.execute(
        select(DailySales.date, func.sum(DailySales.qty_sold), func.sum(DailySales.cogs))
        .where(DailySales.date.between(start, end), DailySales.product_id.in_(pids)).group_by(DailySales.date)
    ):
        r = rows[_bucket_key(d, group)]
        r["sold_qty"] += float(q or 0)
        r["sold_value"] += float(cogs or 0)
    for d, typ, q, v in db.execute(
        select(StockMovement.date, StockMovement.type, func.sum(StockMovement.qty), func.sum(StockMovement.value))
        .where(StockMovement.date.between(start, end), StockMovement.product_id.in_(pids),
               StockMovement.type.in_(["IN", "WASTE", "RETURN"]))
        .group_by(StockMovement.date, StockMovement.type)
    ):
        r = rows[_bucket_key(d, group)]
        key = {"IN": "in", "WASTE": "waste", "RETURN": "return"}[typ]
        r[f"{key}_qty"] += float(q or 0)
        # RETURN.value la tien hoan; quy doi gia von khong luu rieng -> chi dung so luong
        if typ != "RETURN":
            r[f"{key}_value"] += float(v or 0)
    out = []
    for k in sorted(rows):
        r = rows[k]
        out.append({"period": k, "in_qty": int(r["in_qty"]), "in_value": int(r["in_value"]),
                    "sold_qty": int(r["sold_qty"]), "sold_value": int(r["sold_value"]),
                    "waste_qty": int(r["waste_qty"]), "waste_value": int(r["waste_value"]),
                    "return_qty": int(r["return_qty"]),
                    "out_qty": int(r["sold_qty"] + r["waste_qty"] + r["return_qty"])})
    return out


def sales_series(db: Session, start: date, end: date, group: str = "day", category: str | None = None,
                 sku: str | None = None) -> list[dict]:
    q = (select(DailySales.date, func.sum(DailySales.qty_sold), func.sum(DailySales.revenue),
                func.sum(DailySales.cogs), func.sum(DailySales.lost_qty))
         .join(Product, Product.id == DailySales.product_id).where(DailySales.date.between(start, end)))
    if category:
        q = q.where(Product.category.ilike(f"%{category}%"))
    if sku:
        q = q.where(Product.sku == sku.upper())
    rows: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for d, qty, rev, cogs, lost in db.execute(q.group_by(DailySales.date)):
        r = rows[_bucket_key(d, group)]
        r["qty"] += float(qty or 0)
        r["revenue"] += float(rev or 0)
        r["gross_profit"] += float((rev or 0) - (cogs or 0))
        r["lost_qty"] += float(lost or 0)
    return [{"period": k, **{kk: int(vv) for kk, vv in rows[k].items()}} for k in sorted(rows)]


def cost_report(db: Session, start: date, end: date) -> dict:
    days = (end - start).days + 1
    totals = KpiTotals(days=days)
    dt = daily_totals(db, start, end)
    for o in dt.values():
        totals.revenue += o.get("revenue", 0)
        totals.cogs += o.get("cogs", 0)
        totals.units_sold += o.get("sold", 0)
        totals.units_lost += o.get("lost", 0)
        totals.waste_units += o.get("waste_qty", 0)
        totals.waste_cost += o.get("waste_value", 0)
        totals.markdown_loss += o.get("markdown_value", 0)
        totals.return_credit += o.get("return_value", 0)
        totals.purchases_value += o.get("in_value", 0)
    # RETURN.value la tien NCC hoan, khong phai gia von cua hang da tra
    totals.return_cost = float(db.scalar(
        select(func.coalesce(func.sum(StockMovement.qty * StockMovement.unit_cost), 0))
        .where(StockMovement.type == "RETURN", StockMovement.date.between(start, end))) or 0)
    # Lai mat do het hang (gia lap biet lost_qty; cua hang that se uoc tinh tu du bao)
    lost_margin = db.execute(
        select(func.sum(DailySales.lost_qty * (Product.unit_price - Product.unit_cost)))
        .join(Product, Product.id == DailySales.product_id).where(DailySales.date.between(start, end))
    ).scalar()
    totals.lost_margin = float(lost_margin or 0)
    avg, n_snap = snapshots.average(db, start, end)
    if avg is None:  # chua co anh chup (du lieu cu): xap xi bang ton hien tai
        avg = float(db.scalar(select(func.sum(Lot.qty_remaining * Lot.unit_cost)).where(Lot.status == "ACTIVE")) or 0)
    totals.avg_inventory_value = avg
    totals.shrink_cost = float(shrink_value(db, start, end))
    by_cat = []
    for cat, waste in db.execute(
        select(Product.category, func.sum(StockMovement.value)).join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.type == "WASTE", StockMovement.date.between(start, end))
        .group_by(Product.category).order_by(func.sum(StockMovement.value).desc())
    ):
        by_cat.append({"category": cat, "waste_value": int(waste or 0)})
    top_waste = [
        {"sku": s, "name": n, "waste_qty": int(q), "waste_value": int(v)}
        for s, n, q, v in db.execute(
            select(Product.sku, Product.name, func.sum(StockMovement.qty), func.sum(StockMovement.value))
            .join(Product, Product.id == StockMovement.product_id)
            .where(StockMovement.type == "WASTE", StockMovement.date.between(start, end))
            .group_by(Product.sku, Product.name).order_by(func.sum(StockMovement.value).desc()).limit(10)
        )
    ]
    k = summarize(totals)
    k["note_inventory"] = (f"Tồn trung bình lấy từ {n_snap}/{days} ảnh chụp tồn cuối ngày (giá vốn)." if n_snap
                           else "Chưa có ảnh chụp tồn cuối ngày trong kỳ: tạm dùng tồn hiện tại làm xấp xỉ.")
    by_reason = [{"reason": r or "EXPIRED", "label": WASTE_REASONS.get(r or "EXPIRED", r), "waste_qty": int(q or 0),
                  "waste_value": int(v or 0)}
                 for r, q, v in db.execute(
                     select(StockMovement.reason, func.sum(StockMovement.qty), func.sum(StockMovement.value))
                     .where(StockMovement.type == "WASTE", StockMovement.date.between(start, end))
                     .group_by(StockMovement.reason).order_by(func.sum(StockMovement.value).desc()))]
    return {"start": start.isoformat(), "end": end.isoformat(), "kpi": k, "waste_by_category": by_cat,
            "waste_by_reason": by_reason, "top_waste_skus": top_waste, "shrink_value": int(totals.shrink_cost),
            "supplier_scorecard": supplier_scorecard(db, start, end)}


def supplier_scorecard(db: Session, start: date, end: date) -> list[dict]:
    """Diem NCC tren cac don da nhan trong ky: ty le giao du, ty le dung hen, so lan giao date ngan, hang bi tu choi."""
    from app.models import AuditLog, POLine, PurchaseOrder, Supplier

    out: dict[int, dict] = {}
    pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "RECEIVED",
                                                 PurchaseOrder.expected_date.between(start, end)))
    line_sup: dict[int, int] = {}
    for po in pos:
        s = out.setdefault(po.supplier_id, {"supplier_id": po.supplier_id, "orders": 0, "on_time": 0, "ordered": 0,
                                            "received": 0, "short": 0, "rejected": 0, "short_dated": 0})
        s["orders"] += 1
        s["on_time"] += bool(po.received_at and po.received_at.date() <= po.expected_date)
        for l in po.lines:
            line_sup[l.id] = po.supplier_id
            s["ordered"] += l.qty
            s["received"] += l.received_qty or 0
            s["short"] += l.short_qty or 0
            s["rejected"] += l.rejected_qty or 0
            s["short_dated"] += 1 if l.reject_reason == "SHORT_DATED" else 0
    for a in db.scalars(select(AuditLog).where(AuditLog.action == "RECEIVE_SHORT_DATED")):
        sid = line_sup.get(int(a.entity_id)) if a.entity_id and a.entity_id.isdigit() else None
        if sid in out:
            out[sid]["short_dated"] += 1
    names = dict(db.execute(select(Supplier.id, Supplier.name)).all())
    rows = []
    for s in out.values():
        rows.append({**s, "supplier": names.get(s["supplier_id"]),
                     "fill_rate": round(min(s["received"], s["ordered"]) / s["ordered"], 4) if s["ordered"] else None,
                     "on_time_rate": round(s["on_time"] / s["orders"], 4) if s["orders"] else None})
    return sorted(rows, key=lambda r: (r["fill_rate"] or 0, r["on_time_rate"] or 0))


def shrink_value(db: Session, start: date, end: date) -> int:
    """Hao hut = phan ADJUST am RONG theo tung (mat hang, phieu). Kiem date chuyen so giua cac lo cung mat hang
    trong cung phieu nen khong bi tinh la hao hut."""
    rows = db.execute(
        select(StockMovement.product_id, StockMovement.ref, func.sum(StockMovement.value))
        .where(StockMovement.type == "ADJUST", StockMovement.date.between(start, end))
        .group_by(StockMovement.product_id, StockMovement.ref)).all()
    return int(-sum(v for _, _, v in rows if v and v < 0))


def kpi_compare(db: Session, days: int = 30) -> dict:
    end = today() - timedelta(days=1)
    cur = cost_report(db, end - timedelta(days=days - 1), end)
    prev_end = end - timedelta(days=days)
    prev = cost_report(db, prev_end - timedelta(days=days - 1), prev_end)
    return {"current": cur, "previous": prev}


def abc_xyz_report(db: Session) -> dict:
    classes = abc_xyz_classes(db)
    products = {p.sku: p for p in db.scalars(select(Product))}
    matrix: dict[str, dict] = {}
    for c in classes.values():
        m = matrix.setdefault(c.cell, {"cell": c.cell, "skus": 0, "margin_90d": 0.0, "policy": POLICY_BY_CLASS[c.cell]})
        m["skus"] += 1
        m["margin_90d"] += c.margin
    cells = []
    for abc in "ABC":
        for xyz in "XYZ":
            m = matrix.get(abc + xyz, {"cell": abc + xyz, "skus": 0, "margin_90d": 0, "policy": POLICY_BY_CLASS[abc + xyz]})
            m["margin_90d"] = int(round(m["margin_90d"]))
            cells.append(m)
    items = sorted(
        ({"sku": c.sku, "name": products[c.sku].name, "category": products[c.sku].category,
          "cell": "Hàng mới" if is_new(products[c.sku]) else c.cell, "is_new": is_new(products[c.sku]),
          "cv": c.cv, "margin_90d": int(round(c.margin)), "traffic_driver": products[c.sku].is_traffic_driver}
         for c in classes.values()), key=lambda x: -x["margin_90d"])
    return {"window_days": 90, "matrix": cells, "items": items}


NEW_ITEM_DAYS = 56  # 8 tuan: chua du lich su de xep ABC-XYZ hay xet ngung nhap


def is_new(p: Product, d: date | None = None) -> bool:
    return bool(p.listed_date and (d or today()) - p.listed_date < timedelta(days=NEW_ITEM_DAYS))


def delist_report(db: Session, limit: int = 15) -> list[dict]:
    stats, by_sku = sku_stats(db)
    classes = abc_xyz_classes(db)
    # Hang moi duoi 8 tuan it lich su, de roi vao C-Z: khong xet ngung nhap
    stats = [s for s in stats if by_sku[s.sku].status == "ACTIVE" and not is_new(by_sku[s.sku])]
    cands = delist_candidates(stats, classes)
    for c in cands:
        c["product_id"] = by_sku[c["sku"]].id
        c["category"] = by_sku[c["sku"]].category
    return cands[:limit]
