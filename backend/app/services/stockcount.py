"""Kiem ke: dem mu (nguoi dem khong thay so tren he thong), lech thi tao de xuat cho SM duyet."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import today
from app.models import Product
from app.services.inventory import active_lots

# Lich dem theo ABC: A moi tuan, B hai tuan, C moi thang
COUNT_INTERVAL = {"A": 7, "B": 14, "C": 30}
# Ton ao: SKU ban deu (TB >= 1/ngay, co ban >= 60% so ngay) ma >= 3 ngay lien khong ban trong khi so con hang
PHANTOM_ZERO_DAYS = 3

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


def mark_counted(db: Session, skus: list[str], d: date | None = None) -> None:
    """Ghi nhan da dem (ke ca khi khop so) de lap lich dem. Khong doi ton kho."""
    d = d or today()
    for p in db.scalars(select(Product).where(Product.sku.in_([s.upper() for s in skus]))):
        p.last_counted_date = d


def phantom_stock(db: Session) -> list[dict]:
    """Nghi ton ao: ke da trong ma so chua biet. Du bao se giam dan va SKU khong duoc dat lai, nen phai dem."""
    from app.services.history import load_history

    h = load_history(db)
    t = today()
    lots = active_lots(db)
    out = []
    for p in db.scalars(select(Product).where(Product.status == "ACTIVE")):
        on_hand = sum(l.qty_remaining for l in lots.get(p.id, []) if l.sell_by >= t)
        if on_hand <= 0:
            continue
        sales = h.series(p.id, "sales", 28)
        recent, before = sales[-PHANTOM_ZERO_DAYS:], sales[:-PHANTOM_ZERO_DAYS]
        if any(recent) or not before:
            continue
        avg = sum(before) / len(before)
        if avg >= 1 and sum(1 for x in before if x > 0) >= 0.6 * len(before):
            out.append({"sku": p.sku, "name": p.name, "category": p.category,
                        "reason": f"Bán đều ~{avg:.1f}/ngày nhưng {PHANTOM_ZERO_DAYS} ngày liền không bán trong khi sổ còn hàng"})
    return out


def count_due(db: Session, d: date | None = None) -> list[dict]:
    """SKU den lich dem theo ABC (A 7 ngay, B 14, C 30) cong SKU nghi ton ao. Khong kem so ton (dem mu)."""
    from app.services.history import abc_xyz_classes

    d = d or today()
    classes = abc_xyz_classes(db)
    rows = {}
    for p in db.scalars(select(Product).where(Product.status == "ACTIVE").order_by(Product.category, Product.sku)):
        abc = classes[p.sku].abc if p.sku in classes else "B"
        every = COUNT_INTERVAL[abc]
        if p.last_counted_date is None or (d - p.last_counted_date).days >= every:
            last = f"lần đếm trước {p.last_counted_date:%d/%m}" if p.last_counted_date else "chưa đếm lần nào"
            rows[p.sku] = {"sku": p.sku, "name": p.name, "category": p.category,
                           "reason": f"Đến lịch đếm nhóm {abc} ({every} ngày), {last}"}
    for x in phantom_stock(db):
        rows[x["sku"]] = x  # ton ao uu tien hien ly do nay
    return sorted(rows.values(), key=lambda r: (r["category"], r["sku"]))


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
