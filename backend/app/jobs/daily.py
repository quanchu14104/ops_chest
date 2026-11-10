"""Job nen: chuan bi san de xuat de SM mo dashboard la thay "Viec can duyet hom nay".

Chi goi builders (tao PENDING). Khong job nao goi executor.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import audit
from app.proposals import builders, service
from app.services.shelf import pull_list
from datetime import timedelta

from app.clock import today
from app.services import hypotheses, learning, snapshots
from app.services.replenish import suppliers_due

log = logging.getLogger(__name__)
JOB = "job"


def _ref(p, created: bool) -> dict:
    return {"id": p.id, "title": p.title, "created": created}


def run_morning(db: Session) -> dict:
    out: dict = {"expired": service.expire_stale(db), "proposals": [],
                 "hypotheses_evaluated": hypotheses.evaluate_finished(db)}
    # Ton dau ngay = ton cuoi ngay hom qua (chua ban gi): anh chup cho KPI ton trung binh
    snapshots.record(db, today() - timedelta(days=1))
    switched_off = learning.switched_off_categories(db)  # SM da tat thi job khong nhac lai; van de xuat tay duoc
    for pattern in learning.patterns(db):
        if pattern["category"] in switched_off:
            continue
        p, c, _ = builders.order_adjustment(db, pattern["category"], JOB)
        if p:
            out["proposals"].append(_ref(p, c))
    p, c = builders.dispose_expired(db, JOB)
    if p:
        out["proposals"].append(_ref(p, c))
    for p, c in builders.supplier_return(db, JOB):
        out["proposals"].append(_ref(p, c))
    p, c = builders.markdown(db, JOB, days=3)
    if p:
        out["proposals"].append(_ref(p, c))
    for sup in suppliers_due(db):
        p, c, _ = builders.purchase_order(db, sup, JOB)
        if p:
            out["proposals"].append(_ref(p, c))
    db.commit()
    log.info("Morning job: %s", out)
    return out


def run_evening(db: Session) -> dict:
    p, c = builders.markdown(db, JOB, days=0, evening_only=True)
    db.commit()
    return {"proposals": [_ref(p, c)] if p else [], "pull_list": len(pull_list(db))}


def run_closing(db: Session) -> dict:
    """Sau gio dong cua: danh sach rut ke da san sang. Viec go hang la cua nhan vien (xac nhan so thuc go),
    job khong tu doi trang thai lo."""
    lots = pull_list(db)
    if lots:
        audit.log(db, JOB, "PULL_LIST_READY", "lot", None, {"lots": len(lots)})
        db.commit()
    return {"pull_list": len(lots)}
