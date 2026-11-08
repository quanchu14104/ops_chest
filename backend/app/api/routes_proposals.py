"""API de xuat. Duyet/tu choi CHI qua cac endpoint nay, yeu cau user role=manager."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, require_manager
from app.db import get_db
from app.jobs.daily import run_evening, run_morning
from app.models import Proposal, User
from app.proposals import service
from app.proposals.views import to_dict

router = APIRouter(prefix="/api/proposals")


def _err(e: service.ProposalError):
    raise HTTPException(e.status_code, e.message) from e


@router.get("")
def list_proposals(status: str | None = None, type: str | None = None, limit: int = Query(100, le=500),
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(Proposal).order_by(Proposal.id.desc()).limit(limit)
    if status:
        q = q.where(Proposal.status.in_([s.strip().upper() for s in status.split(",")]))
    if type:
        q = q.where(Proposal.type == type.upper())
    return [to_dict(p) for p in db.scalars(q)]


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.acceptance_stats(db)


class CreateIn(BaseModel):
    type: str  # PURCHASE_ORDER / MARKDOWN / RETURN / DISPOSE / DELIST
    supplier: str | None = None
    lot_ids: list[int] | None = None
    sku: str | None = None


@router.post("/create")
def create(body: CreateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Tao de xuat tu giao dien (van la PENDING, van can SM duyet)."""
    from app.proposals import builders
    from app.services.replenish import get_supplier

    who = f"user:{user.username}"
    t = body.type.upper()
    created: list = []
    if t == "PURCHASE_ORDER":
        sup = get_supplier(db, body.supplier or "")
        if not sup:
            raise HTTPException(404, "Không tìm thấy nhà cung cấp")
        p, c, sug = builders.purchase_order(db, sup, who)
        if not p:
            raise HTTPException(422, "Không cần đặt hàng lúc này: tồn còn hạn + hàng đang về đủ phủ nhu cầu dự báo.")
        created = [p]
    elif t == "MARKDOWN":
        p, _ = builders.markdown(db, who, lot_ids=body.lot_ids, days=7 if body.lot_ids else 3)
        created = [p] if p else []
    elif t == "RETURN":
        created = [p for p, _ in builders.supplier_return(db, who, lot_ids=body.lot_ids)]
    elif t == "DISPOSE":
        p, _ = builders.dispose_expired(db, who)
        created = [p] if p else []
    elif t == "DELIST":
        p, _, err = builders.delist(db, body.sku or "", who)
        if not p:
            raise HTTPException(422, err)
        created = [p]
    else:
        raise HTTPException(422, "Loại đề xuất không hợp lệ")
    db.commit()
    if not created:
        raise HTTPException(422, "Không có lô nào phù hợp với loại đề xuất này (phương án khác có lợi hơn).")
    return [to_dict(p) for p in created]


@router.get("/{pid}")
def get_proposal(pid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = db.get(Proposal, pid)
    if not p:
        raise HTTPException(404, "Không tìm thấy đề xuất")
    return to_dict(p)


class EditIn(BaseModel):
    lines: list[dict] | None = None
    items: list[dict] | None = None
    note: str | None = None

    def edits(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


@router.patch("/{pid}")
def edit_proposal(pid: int, body: EditIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    try:
        return to_dict(service.edit(db, pid, body.edits(), user))
    except service.ProposalError as e:
        _err(e)


class ApproveIn(BaseModel):
    note: str | None = None
    edits: EditIn | None = None


@router.post("/{pid}/approve")
def approve(pid: int, body: ApproveIn | None = None, db: Session = Depends(get_db),
            user: User = Depends(require_manager)):
    body = body or ApproveIn()
    try:
        return to_dict(service.approve(db, pid, user, body.note, body.edits.edits() if body.edits else None))
    except service.ProposalError as e:
        _err(e)


class RejectIn(BaseModel):
    reason: str


@router.post("/{pid}/reject")
def reject(pid: int, body: RejectIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    try:
        return to_dict(service.reject(db, pid, user, body.reason))
    except service.ProposalError as e:
        _err(e)


class GenerateIn(BaseModel):
    kind: str = "morning"  # morning / evening


@router.post("/generate")
def generate(body: GenerateIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Chay quet ngay (giong job 06:30/17:00). Chi tao de xuat PENDING."""
    if body.kind == "evening":
        return run_evening(db)
    return run_morning(db)

