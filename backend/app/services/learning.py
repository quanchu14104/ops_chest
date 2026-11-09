"""Doc lich su sua de xuat dat hang de tim thoi quen cua Store Manager."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.edit_learning import EditObservation, detect_patterns
from app.models import OrderAdjustment, Product, Proposal

def active_adjustments(db: Session) -> dict[str, OrderAdjustment]:
    return {a.category: a for a in db.scalars(select(OrderAdjustment).where(OrderAdjustment.active.is_(True)))}


def observations(db: Session) -> list[EditObservation]:
    """Moi dong da sua la mot quan sat: so chot cuoi cung so voi so he thong goi y, du sua qua bao nhieu buoc."""
    category = dict(db.execute(select(Product.sku, Product.category)).all())
    out = []
    # Chi tinh don da duyet: ban sua chua chot co the bi SM doi y
    for p in db.scalars(select(Proposal).where(Proposal.type == "PURCHASE_ORDER", Proposal.status == "EXECUTED")):
        if not p.sm_edits:
            continue
        for line in p.payload["lines"]:
            suggested = line.get("suggested_qty")  # dong SM tu them co suggested_qty = 0: khong co gi de so
            if suggested and line["qty"] != suggested and line["sku"] in category:
                out.append(EditObservation(category[line["sku"]], p.id, float(line["qty"]) / float(suggested)))
    return out


def switched_off_categories(db: Session) -> set[str]:
    return set(db.scalars(select(OrderAdjustment.category).where(OrderAdjustment.active.is_(False))))


def patterns(db: Session) -> list[dict]:
    """Nhom da co he so dang chay bi loai: cac lan sua cu duoc tinh tren goi y truoc khi co he so."""
    active = active_adjustments(db)
    return [p for p in detect_patterns(observations(db)) if p["category"] not in active]
