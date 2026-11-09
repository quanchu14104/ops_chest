"""Kiem ke: dem mu (nguoi dem khong thay so tren he thong), lech thi tao de xuat cho SM duyet."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product
from app.services.inventory import active_lots

LARGE_GAP_PCT = 0.2
LARGE_GAP_MIN_UNITS = 5


class StockCountError(Exception):
    pass


def sheet(db: Session, category: str | None = None) -> list[dict]:
    """Phieu dem. Co y KHONG kem so ton: nguoi dem nhin thay so se co xu huong dem cho khop."""
    q = select(Product).where(Product.status == "ACTIVE").order_by(Product.category, Product.sku)
    if category:
        q = q.where(Product.category.ilike(f"%{category}%"))
    return [{"sku": p.sku, "name": p.name, "category": p.category} for p in db.scalars(q)]


def is_large_gap(system_qty: int, diff: int) -> bool:
    return abs(diff) >= max(LARGE_GAP_MIN_UNITS, LARGE_GAP_PCT * system_qty)


def diffs(db: Session, counted: dict[str, int]) -> list[dict]:
    if not counted:
        raise StockCountError("Chưa có dòng nào được đếm.")
    if any(int(v) < 0 for v in counted.values()):
        raise StockCountError("Số đếm không được âm.")
    products = {p.sku: p for p in db.scalars(select(Product).where(Product.sku.in_([s.upper() for s in counted])))}
    missing = [s for s in counted if s.upper() not in products]
    if missing:
        raise StockCountError(f"Không tìm thấy SKU: {', '.join(missing)}")
    lots = active_lots(db, [p.id for p in products.values()])
    out = []
    for sku, qty in counted.items():
        p = products[sku.upper()]
        system = sum(l.qty_remaining for l in lots.get(p.id, []))
        if int(qty) != system:
            out.append({"product_id": p.id, "sku": p.sku, "name": p.name, "system_qty": system, "counted_qty": int(qty),
                        "diff": int(qty) - system, "unit_cost": p.unit_cost, "value": (int(qty) - system) * p.unit_cost})
    return out
