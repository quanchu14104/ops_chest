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
from app.models import DemandHypothesis, OrderAdjustment, Product, Proposal, SupplierReturn, User
from app.proposals import builders
from app.proposals.views import to_dict
from app.services import datecheck, hypotheses, learning, returns, shelf, stockcount

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
def stock_count_sheet(category: str | None = None, due: bool = False, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    """due=true: chi SKU den lich dem theo ABC va SKU nghi ton ao (kem ly do, khong kem so ton)."""
    return stockcount.count_due(db) if due else stockcount.sheet(db, category)


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
    stockcount.mark_counted(db, [l.sku for l in body.lines])
    db.commit()
    return {"counted": n, "proposal": to_dict(p) if p else None}


@router.get("/date-check/sheet")
def date_check_sheet(freshness: str | None = None, category: str | None = None, db: Session = Depends(get_db),
                     user: User = Depends(current_user)):
    """Phieu kiem date: SKU co lo sap toi ngay ban cuoi va cac HSD tren so (khong kem so luong)."""
    return {"due_today": datecheck.due_classes(), "lines": datecheck.sheet(db, freshness, category)}


class DateLine(BaseModel):
    sku: str
    expiry_date: str
    counted_qty: int


class DateCheckIn(BaseModel):
    lines: list[DateLine]
    note: str | None = None


@router.post("/date-checks")
def submit_date_check(body: DateCheckIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Nhan vien gui so dem theo HSD. Khong doi ton kho: lech thi tao de xuat cap lo cho Store Manager duyet."""
    try:
        p, n = builders.date_check(db, [l.model_dump() for l in body.lines], f"user:{user.username}", body.note)
    except (datecheck.DateCheckError, ValueError) as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    stockcount.mark_counted(db, [l.sku for l in body.lines])
    db.commit()
    return {"counted": n, "proposal": to_dict(p) if p else None}


@router.get("/shelf/pull-list")
def get_pull_list(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Danh sach rut ke cuoi ngay (lo het ngay ban). Khong kem so tren so."""
    return {"closing_hour": settings.closing_hour, "lots": shelf.pull_list(db)}


class PullLine(BaseModel):
    lot_id: int
    pulled_qty: int


class PullIn(BaseModel):
    lines: list[PullLine]


@router.post("/shelf/pull")
def confirm_pull(body: PullIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Nhan vien xac nhan so thuc go khoi ke. Bat buoc, khong can duyet (co audit). Lo chuyen PULLED: khong con
    ban, khong tinh vao don dat hang. But toan ghi huy van la de xuat cho Store Manager duyet."""
    try:
        out = shelf.confirm_pull(db, [l.model_dump() for l in body.lines], user.username)
    except shelf.PullError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    p, _ = builders.dispose_expired(db, "job")
    db.commit()
    return {**out, "proposal": to_dict(p) if p else None}


class WriteOffLine(BaseModel):
    lot_id: int
    qty: int
    reason: str


class WriteOffIn(BaseModel):
    lines: list[WriteOffLine]
    note: str | None = None


@router.post("/write-offs")
def write_off(body: WriteOffIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Bao huy hang vo/hong/loi NCC kem ly do. Chi tao de xuat; SM duyet moi tru ton."""
    try:
        p = builders.write_off(db, [l.model_dump() for l in body.lines], f"user:{user.username}", body.note)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    db.commit()
    return to_dict(p)


@router.get("/supplier-returns")
def list_returns(status: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(SupplierReturn).order_by(SupplierReturn.id.desc()).limit(100)
    if status:
        q = q.where(SupplierReturn.status.in_([s.strip().upper() for s in status.split(",")]))
    return [returns.view(r) for r in db.scalars(q)]


def _return_action(db: Session, fn):
    try:
        out = fn()
    except returns.ReturnError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    db.commit()
    return out


@router.post("/supplier-returns/{rid}/confirm")
def return_confirm(rid: int, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    """NCC xac nhan se lay hang. Chua ghi tien."""
    return _return_action(db, lambda: returns.view(returns.confirm(db, rid, user)))


class PickupLine(BaseModel):
    lot_id: int
    qty: int


class PickupIn(BaseModel):
    lines: list[PickupLine] = []


@router.post("/supplier-returns/{rid}/pickup")
def return_pickup(rid: int, body: PickupIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    """NCC da lay hang: SM nhap so thuc nhan. Luc nay moi ghi RETURN (tien hoan) hoac nhap hang doi."""
    return _return_action(db, lambda: returns.view(returns.pick_up(db, rid, {l.lot_id: l.qty for l in body.lines}, user)))


class CreditIn(BaseModel):
    amount: int | None = None


@router.post("/supplier-returns/{rid}/credited")
def return_credited(rid: int, body: CreditIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    return _return_action(db, lambda: returns.view(returns.mark_credited(db, rid, user, body.amount)))


class RefuseIn(BaseModel):
    reason: str


@router.post("/supplier-returns/{rid}/refuse")
def return_refuse(rid: int, body: RefuseIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    """NCC tu choi: lo quay lai ban; he thong xet lai phuong an giam gia (tao de xuat neu co loi)."""
    def run():
        r, lots = returns.refuse(db, rid, body.reason, user)
        db.flush()
        p, _ = builders.markdown(db, "job", lot_ids=lots, days=60) if lots else (None, False)
        return {**returns.view(r), "markdown_proposal": to_dict(p) if p else None}
    return _return_action(db, run)


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
