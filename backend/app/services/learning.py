"""Doc lich su sua de xuat dat hang de tim thoi quen cua Store Manager."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.edit_learning import EditObservation, detect_patterns
from app.models import OrderAdjustment, Product, Proposal

_QTY_FIELD = re.compile(r"^lines\[(.+)\]\.qty$")


def active_adjustments(db: Session) -> dict[str, OrderAdjustment]:
    return {a.category: a for a in db.scalars(select(OrderAdjustment).where(OrderAdjustment.active.is_(True)))}


def observations(db: Session) -> list[EditObservation]:
    category = dict(db.execute(select(Product.sku, Product.category)).all())
    out = []
    # Chi tinh don da duyet: ban sua chua chot co the bi SM doi y
    for p in db.scalars(select(Proposal).where(Proposal.type == "PURCHASE_ORDER", Proposal.status == "EXECUTED")):
        for edit in p.sm_edits or []:
            for c in edit.get("changes", []):
                m = _QTY_FIELD.match(c.get("field", ""))
                if not m or m.group(1) not in category or not c.get("from"):
                    continue
                out.append(EditObservation(category[m.group(1)], p.id, float(c["to"]) / float(c["from"])))
    return out


def patterns(db: Session) -> list[dict]:
    """Nhom da co he so dang chay bi loai: cac lan sua cu duoc tinh tren goi y truoc khi co he so."""
    active = active_adjustments(db)
    return [p for p in detect_patterns(observations(db)) if p["category"] not in active]
