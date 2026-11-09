"""Du lieu mau chi danh cho demo: lich su SM sua don, de tinh nang hoc thoi quen co gi de hien."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.clock import today
from app.models import Product, Proposal, Supplier

DEMO_ROUNDS = 6
DEMO_RATIO = 0.8


def seed_edit_history(db: Session, actor: str) -> dict:
    """6 don da duyet trong qua khu, moi don SM giam 2 dong cua cung mot nhom khoang 20%. Goi lai khong nhan doi."""
    existing = db.scalar(select(func.count()).select_from(Proposal).where(Proposal.dedupe_key.like("DEMO-EDIT:%")))
    if existing:
        return {"created": 0, "message": "Lịch sử sửa mẫu đã có sẵn."}
    category = db.scalar(select(Product.category).where(Product.status == "ACTIVE", Product.freshness_class == "FRESH")
                         .group_by(Product.category).order_by(func.count().desc()))
    products = db.scalars(select(Product).where(Product.category == category, Product.status == "ACTIVE")
                          .order_by(Product.sku).limit(2)).all()
    sup = db.get(Supplier, products[0].supplier_id)
    t = today()
    for i in range(DEMO_ROUNDS):
        at = datetime.combine(t - timedelta(days=(DEMO_ROUNDS - i) * 2), time(7, 0))
        lines, changes = [], []
        for p in products:
            suggested = (10 + i) * max(1, p.pack_size)
            final = int(round(suggested * DEMO_RATIO))
            lines.append({"product_id": p.id, "sku": p.sku, "name": p.name, "qty": final, "suggested_qty": suggested,
                          "pack_size": p.pack_size, "unit_cost": p.unit_cost, "line_value": final * p.unit_cost})
            changes.append({"field": f"lines[{p.sku}].qty", "from": suggested, "to": final})
        payload = {"supplier_id": sup.id, "supplier_name": sup.name, "supplier_email": sup.email,
                   "expected_date": t.isoformat(), "min_order_value": sup.min_order_value, "lines": lines,
                   "total_value": sum(l["line_value"] for l in lines), "note": ""}
        db.add(Proposal(type="PURCHASE_ORDER", status="EXECUTED", title=f"[Mẫu demo] Đặt hàng {sup.name}",
                        rationale="Dữ liệu mẫu cho demo học thói quen sửa số lượng.", evidence={}, payload=payload,
                        original_payload=payload, sm_edits=[{"by": actor, "at": at.isoformat(), "changes": changes}],
                        est_value=payload["total_value"], created_by="sim", created_at=at, decided_by=actor, decided_at=at,
                        executed_at=at, dedupe_key=f"DEMO-EDIT:{i}"))
    audit.log(db, actor, "SIM_DEMO_EDITS", "proposal", None, {"category": category, "rounds": DEMO_ROUNDS})
    db.commit()
    return {"created": DEMO_ROUNDS, "category": category}
