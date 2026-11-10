"""Kiem date: dem theo TUNG HSD nhin thay tren ke, khong chi theo SKU.

POS chi biet SKU va khach hay lay lo moi o phia trong, nen so theo lo luon lech voi ke: so ghi lo cu da het,
tren ke lo cu van con. Khi do lo sap het han khong hien trong bao cao can date va qua han ngay tren ke ma
so khong biet. Phieu kiem date liet ke cac HSD so dang co (KHONG kem so luong: dem mu) va cho them HSD
chua co trong so. Chenh lech thanh de xuat STOCK_ADJUST cap lo, Store Manager duyet.

Lich: hang tuoi moi ngay, hang ngan ngay moi thu Hai, hang dai ngay ngay 1 hang thang. Kiem ke theo SKU
(services/stockcount.py) van dung cho hang dai ngay con xa han.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.clock import today
from app.models import Lot, Product

# Lo con <= N ngay toi ngay ban cuoi thi SKU vao phieu kiem date
HORIZON = {"FRESH": 2, "SHORT": 7, "LONG": 30}
CLASS_LABEL = {"FRESH": "hàng tươi", "SHORT": "hàng ngắn ngày", "LONG": "hàng dài ngày"}


class DateCheckError(Exception):
    pass


def due_classes(d: date | None = None) -> list[str]:
    d = d or today()
    out = ["FRESH"]
    if d.weekday() == 0:
        out.append("SHORT")
    if d.day == 1:
        out.append("LONG")
    return out


def sheet(db: Session, freshness: str | None = None, category: str | None = None) -> list[dict]:
    """SKU co lo sap toi ngay ban cuoi, kem cac HSD tren so (khong kem so luong)."""
    t = today()
    classes = [freshness.upper()] if freshness else list(HORIZON)
    q = (select(Lot).options(joinedload(Lot.product)).join(Product)
         .where(Lot.status == "ACTIVE", Lot.qty_remaining > 0, Product.status == "ACTIVE",
                Product.freshness_class.in_(classes)))
    if category:
        q = q.where(Product.category.ilike(f"%{category}%"))
    by_pid: dict[int, list[Lot]] = defaultdict(list)
    for lot in db.scalars(q).unique():
        by_pid[lot.product_id].append(lot)
    out = []
    for lots in by_pid.values():
        p = lots[0].product
        if min(l.sell_by for l in lots) > t + timedelta(days=HORIZON[p.freshness_class]):
            continue
        out.append({"sku": p.sku, "name": p.name, "category": p.category, "freshness_class": p.freshness_class,
                    "dates": sorted({l.expiry_date.isoformat() for l in lots})})
    out.sort(key=lambda r: (r["category"], r["sku"]))
    return out


def diffs(db: Session, lines: list[dict]) -> list[dict]:
    """lines: [{sku, expiry_date, counted_qty}]. Voi moi SKU co trong phieu, HSD tren so ma khong duoc ghi
    nghia la dem duoc 0 (nguoi dem da xem het ke cua SKU do)."""
    if not lines:
        raise DateCheckError("Chưa có dòng nào được đếm.")
    counted: dict[tuple[str, date], int] = defaultdict(int)
    for ln in lines:
        q = int(ln["counted_qty"])
        if q < 0:
            raise DateCheckError("Số đếm không được âm.")
        raw = ln.get("expiry_date")
        if not raw:
            raise DateCheckError(f"Thiếu HSD cho dòng {ln.get('sku')}.")
        exp = date.fromisoformat(raw) if isinstance(raw, str) else raw
        counted[(str(ln["sku"]).upper(), exp)] += q
    skus = sorted({s for s, _ in counted})
    products = {p.sku: p for p in db.scalars(select(Product).where(Product.sku.in_(skus)))}
    missing = [s for s in skus if s not in products]
    if missing:
        raise DateCheckError(f"Không tìm thấy SKU: {', '.join(missing)}")
    out = []
    for sku in skus:
        p = products[sku]
        book: dict[date, int] = defaultdict(int)
        for lot in db.scalars(select(Lot).where(Lot.product_id == p.id, Lot.status == "ACTIVE", Lot.qty_remaining > 0)):
            book[lot.expiry_date] += lot.qty_remaining
        dates = sorted(set(book) | {e for s, e in counted if s == sku})
        for exp in dates:
            sys_q, cnt = book.get(exp, 0), counted.get((sku, exp), 0)
            if sys_q == cnt:
                continue
            out.append({"product_id": p.id, "sku": p.sku, "name": p.name, "expiry_date": exp.isoformat(),
                        "system_qty": sys_q, "counted_qty": cnt, "diff": cnt - sys_q, "unit_cost": p.unit_cost,
                        "value": (cnt - sys_q) * p.unit_cost, "new_date": exp not in book})
    return out
