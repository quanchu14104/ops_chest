"""Sinh 1 nam lich su (chinh sach 'kinh nghiem', truoc khi co Ops Chest) va ghi vao DB.

    uv run python -m app.sim.seed --reset
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timedelta
from datetime import time as dtime

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app import clock
from app.auth import hash_password
from app.clock import today
from app.db import SessionLocal
from app.db_init import migrate
from app.db_init import reset as reset_db
from app.models import (AppMeta, CategoryPolicy, DailySales, InventorySnapshot, Lot, POLine, Product, PurchaseOrder, StockMovement, Supplier,
                        SupplierAgreement, SupplierClosure, User)
from app.sim.backtest import initial_stock
from app.sim import frn
from app.sim.catalog import PULL_DAYS, build_catalog, category_policy
from app.sim.demand import FrnDemand
from app.sim.frn_catalog import build_frn_catalog, frn_category_policy
from app.sim.policies import BaselinePolicy
from app.sim.store_sim import StoreSim

# Tai khoan demo (chi dung cho moi truong gia lap)
DEMO_USERS = [
    ("quanly", "Trần Minh Anh", "manager", "quanly123"),
    ("nhanvien", "Lê Văn Bình", "staff", "nhanvien123"),
]


def _chunks(rows: list[dict], n: int = 5000):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def seed(days: int | None = None, seed_value: int = 7, reset: bool = False, source: str = "frn") -> dict:
    """source='frn': nhu cau THAT cua mot diem ban FreshRetailNet-50K, van hanh (lo, don, so sach) mo phong bang chinh
    sach 'kinh nghiem'; dong ho dat o ngay ngay sau moc cat cua FRN. source='synthetic': the gioi gia lap cu (bo test
    quy tac nghiep vu can Tet, hang dai ngay, lich nghi NCC)."""
    t0 = time.perf_counter()
    if source == "frn" and not frn.available():
        print("Chưa có dữ liệu FRN (app/sim/data/frn/stores_daily.csv.gz), dùng dữ liệu giả lập.")
        source = "synthetic"
    if reset:
        reset_db()
    migrate()
    if source == "frn":
        store, k = frn.store(), frn.k_scale()
        cutoff = int(frn.meta().get("cutoff_day", 89))
        days = cutoff + 1 if days is None else min(days, cutoff + 1)
        start, end = store.dates[cutoff + 1 - days], store.dates[cutoff]
        clock.set_today(store.dates[cutoff + 1])
        suppliers, products = build_frn_catalog(store, k)
        sim = StoreSim(suppliers, products, seed=seed_value, record=True, demand=FrnDemand(store, k))
    else:
        days = days or 365
        end = today() - timedelta(days=1)
        start = end - timedelta(days=days - 1)
        suppliers, products = build_catalog()
        sim = StoreSim(suppliers, products, seed=seed_value, record=True)
    initial_stock(sim, start)
    sim.run(start, days, BaselinePolicy())

    db: Session = SessionLocal()
    try:
        if db.scalar(select(Product.id).limit(1)):
            raise SystemExit("DB đã có dữ liệu. Chạy lại với --reset để xóa và seed lại.")
        sup_ids = {}
        for s in suppliers:
            row = Supplier(code=s.code, name=s.name, email=s.email, phone=s.phone, lead_time_days=s.lead_time_days,
                           order_weekdays=s.order_weekdays, min_order_value=s.min_order_value,
                           delivery_weekdays=s.delivery_weekdays)
            db.add(row)
            db.flush()
            for a, b, why in s.closures:
                db.add(SupplierClosure(supplier_id=row.id, start_date=a, end_date=b, reason=why))
            sup_ids[s.code] = row.id
            notes = ("Không nhận trả hàng cận hạn." if not s.accepts_return else
                     "Nhận trả hàng cận hạn nếu báo trước; đổi hàng mới (đổi date) khi thu hồi." if s.return_mode == "EXCHANGE"
                     else "Nhận trả hàng cận hạn nếu báo trước; hoàn tiền trừ vào đơn kế tiếp.")
            db.add(SupplierAgreement(supplier_id=row.id, discount_pct=s.discount_pct,
                                     accepts_near_expiry_return=s.accepts_return,
                                     return_min_days_before_expiry=s.return_min_days,
                                     return_credit_pct=s.return_credit_pct, return_mode=s.return_mode,
                                     valid_from=start,
                                     valid_to=end + timedelta(days=365), notes=notes))
        pid = {}
        # Cua hang van dem theo lich: rai ngay dem gan nhat trong 7 ngay qua de demo khong bao "moi SKU den lich"
        for i, p in enumerate(products):
            row = Product(sku=p.sku, name=p.name, category=p.category, freshness_class=p.freshness_class,
                          shelf_life_days=p.shelf_life_days, unit_cost=p.unit_cost, unit_price=p.unit_price,
                          pack_size=p.pack_size, supplier_id=sup_ids[p.supplier_code],
                          is_traffic_driver=p.is_traffic_driver, substitute_skus=p.substitutes,
                          pull_days_before_expiry=PULL_DAYS[p.freshness_class],
                          max_stock_qty=p.max_stock_qty, min_display_qty=p.min_display_qty, listed_date=start,
                          last_counted_date=end - timedelta(days=i % 7))
            db.add(row)
            db.flush()
            pid[p.sku] = row.id

        for cat in sorted({p.category for p in products}):
            pol = frn_category_policy(cat) if source == "frn" else category_policy(cat)
            db.add(CategoryPolicy(category=cat, markdown_allowed=pol["markdown_allowed"],
                                  max_markdown_pct=pol["max_markdown_pct"], daypart_shares=pol["daypart_shares"],
                                  markdown_hour=pol["markdown_hour"],
                                  note="Trần giảm giá là cấu hình demo, cần đối chiếu Nghị định 81/2018/NĐ-CP."))
        line_ids = {}
        pending_codes = {o.po_code for o in sim.pipeline}
        for code, rec in sim.pos.items():
            pending = code in pending_codes
            po = PurchaseOrder(code=code, supplier_id=sup_ids[rec.supplier], status="SENT" if pending else "RECEIVED",
                               order_date=rec.order_date, expected_date=rec.arrival,
                               total_value=sum(q * c for _, q, c in rec.lines),
                               received_at=None if pending else datetime.combine(rec.arrival, dtime(8, 0)))
            for sku, q, c in rec.lines:
                po.lines.append(POLine(product_id=pid[sku], qty=q, unit_cost=c, received_qty=None if pending else q))
            db.add(po)
        db.flush()
        for line, code in db.execute(select(POLine, PurchaseOrder.code).join(PurchaseOrder)):
            line_ids[(code, line.product_id)] = line.id

        for sku, lots in sim.lots.items():
            for l in lots:
                db.add(Lot(product_id=pid[sku], qty_received=l.qty, qty_remaining=l.qty, received_date=l.received,
                           expiry_date=l.expiry, unit_cost=l.unit_cost, markdown_pct=0.0,
                           po_line_id=line_ids.get((l.po_code, pid[sku])), status="ACTIVE"))

        for chunk in _chunks([{**{k: v for k, v in r.items() if k != "sku"}, "product_id": pid[r["sku"]]}
                              for r in sim.sales_rows]):
            db.execute(insert(DailySales), chunk)
        for chunk in _chunks([{**{k: v for k, v in r.items() if k != "sku"}, "product_id": pid[r["sku"]]}
                              for r in sim.movements]):
            db.execute(insert(StockMovement), chunk)
        db.execute(insert(InventorySnapshot), [{"date": x["date"], "value": int(round(x["inv_value"])),
                                                "units": 0} for x in sim.daily_kpi])

        if not db.scalar(select(User.id).limit(1)):
            for u, name, role, pw in DEMO_USERS:
                db.add(User(username=u, full_name=name, role=role, password_hash=hash_password(pw)))
        db.merge(AppMeta(key="seeded_for_date", value=today().isoformat()))
        db.merge(AppMeta(key="seed_policy", value=BaselinePolicy.name))
        db.merge(AppMeta(key="data_source", value=source))
        if source == "frn":
            db.merge(AppMeta(key="frn_store", value=str(store.store_id)))
            db.merge(AppMeta(key=clock.SIM_CLOCK_KEY, value=today().isoformat()))
        db.commit()
    finally:
        db.close()
    return {"source": source, "today": today().isoformat(), "days": days, "start": start.isoformat(), "end": end.isoformat(), "products": len(products),
            "sales_rows": len(sim.sales_rows), "movements": len(sim.movements), "purchase_orders": len(sim.pos),
            "open_lots": sum(len(v) for v in sim.lots.values()), "seconds": round(time.perf_counter() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="Mặc định: FRN 90 ngày, giả lập 365 ngày")
    ap.add_argument("--source", choices=["frn", "synthetic"], default="frn",
                    help="frn: nhu cầu thật FreshRetailNet-50K (mặc định); synthetic: thế giới giả lập cũ")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--reset", action="store_true", help="Xóa toàn bộ bảng rồi seed lại")
    args = ap.parse_args()
    print(seed(args.days, args.seed, args.reset, args.source))


if __name__ == "__main__":
    main()
