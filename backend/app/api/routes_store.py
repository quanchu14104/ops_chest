"""Gia thuyet nhu cau, he so hoc tu phan sua, tua nhanh demo."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.agent import vision
from app.auth import current_user, require_manager
from app.config import settings
from app.db import get_db
from app.models import DemandHypothesis, OrderAdjustment, Product, Proposal, User
from app.proposals import builders
from app.proposals.views import to_dict
from app.services import hypotheses, learning, stockcount

router = APIRouter(prefix="/api")


def _release_dedupe(db: Session, proposal_id: int | None) -> None:
    """Da huy/tat thi de xuat cu khong con chan viec de xuat lai dung noi dung do."""
    p = db.get(Proposal, proposal_id) if proposal_id else None
    if p:
        p.dedupe_key = None


@router.get("/hypotheses")
def list_hypotheses(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return hypotheses.list_views(db)


@router.post("/hypotheses/{hid}/cancel")
def cancel_hypothesis(hid: int, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    x = db.get(DemandHypothesis, hid)
    if not x:
        raise HTTPException(404, "Không tìm thấy giả thuyết")
    if x.status != "ACTIVE":
        raise HTTPException(409, "Giả thuyết này không còn hiệu lực.")
    x.status = "CANCELLED"
    _release_dedupe(db, x.proposal_id)
    audit.log(db, user.username, "HYPOTHESIS_CANCELLED", "demand_hypothesis", x.id)
    db.commit()
    return hypotheses.view(x)


@router.get("/learning/order-edits")
def order_edits(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"patterns": learning.patterns(db),
            "active": [{"id": a.id, "category": a.category, "factor": a.factor, "reason": a.reason}
                       for a in learning.active_adjustments(db).values()]}


class AdjustIn(BaseModel):
    category: str


@router.post("/learning/propose")
def propose_adjustment(body: AdjustIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p, _, err = builders.order_adjustment(db, body.category, f"user:{user.username}")
    db.commit()
    if not p:
        raise HTTPException(422, err)
    return to_dict(p)


@router.post("/learning/adjustments/{aid}/deactivate")
def deactivate_adjustment(aid: int, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    a = db.get(OrderAdjustment, aid)
    if not a or not a.active:
        raise HTTPException(404, "Không tìm thấy hệ số đang chạy")
    a.active = False
    _release_dedupe(db, a.proposal_id)
    audit.log(db, user.username, "ORDER_ADJUST_DEACTIVATED", "order_adjustment", a.id, {"category": a.category})
    db.commit()
    return {"id": a.id, "active": False}


@router.get("/stock-count/sheet")
def stock_count_sheet(category: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return stockcount.sheet(db, category)


class CountLine(BaseModel):
    sku: str
    counted_qty: int


class CountIn(BaseModel):
    lines: list[CountLine]
    note: str | None = None


@router.post("/stock-counts")
def submit_count(body: CountIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Nhan vien gui so dem. Khong doi ton kho: lech thi tao de xuat cho Store Manager duyet."""
    try:
        p, n = builders.stock_adjust(db, {l.sku: l.counted_qty for l in body.lines}, f"user:{user.username}", body.note)
    except stockcount.StockCountError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    db.commit()
    return {"counted": n, "proposal": to_dict(p) if p else None}


class VisionIn(BaseModel):
    image_base64: str
    mime_type: str
    sku: str | None = None


@router.post("/vision/expiry")
def vision_expiry(body: VisionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Doc HSD tu anh tem de dien san form. Khong ghi du lieu, khong luu anh."""
    product = db.scalar(select(Product).where(Product.sku == body.sku.upper())) if body.sku else None
    try:
        return vision.read_expiry(body.image_base64, body.mime_type, product.shelf_life_days if product else None)
    except vision.VisionError as e:
        raise HTTPException(422, str(e)) from e


def _sim_on() -> None:
    if not settings.enable_sim_controls:
        raise HTTPException(403, "Tính năng tua nhanh đang tắt (ENABLE_SIM_CONTROLS=false).")


class AdvanceIn(BaseModel):
    days: int = 1
    realize_hypotheses: bool = True


@router.post("/sim/advance")
def sim_advance(body: AdvanceIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    _sim_on()
    from app.sim.advance import advance

    try:
        return advance(db, body.days, user.username, body.realize_hypotheses)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/sim/demo-edit-history")
def sim_demo_edits(db: Session = Depends(get_db), user: User = Depends(require_manager)):
    _sim_on()
    from app.sim.demo import seed_edit_history

    return seed_edit_history(db, user.username)
