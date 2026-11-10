"""Anh chup gia tri ton cuoi ngay. Ton trung binh cua mot ky lay tu day, khong lay ton hien tai."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import InventorySnapshot, Lot

# Hang con tren so (ke ca da rut ke cho ghi huy, dang cho NCC lay): von van nam trong hang
BOOK_STATUSES = ("ACTIVE", "PULLED", "RETURN_PENDING")


def record(db: Session, d: date) -> InventorySnapshot:
    value, units = db.execute(
        select(func.coalesce(func.sum(Lot.qty_remaining * Lot.unit_cost), 0), func.coalesce(func.sum(Lot.qty_remaining), 0))
        .where(Lot.status.in_(BOOK_STATUSES))).one()
    row = db.get(InventorySnapshot, d) or InventorySnapshot(date=d)
    row.value, row.units = int(value), int(units)
    db.merge(row)
    return row


def average(db: Session, start: date, end: date) -> tuple[float | None, int]:
    """(gia tri ton trung binh, so ngay co anh chup) trong [start, end]."""
    avg, n = db.execute(select(func.avg(InventorySnapshot.value), func.count())
                        .where(InventorySnapshot.date.between(start, end))).one()
    return (float(avg) if avg is not None else None), int(n or 0)
