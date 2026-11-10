"""Rut ke hang het han: viec BAT BUOC cua ca lam, khong phai quyet dinh cho duyet.

Ban hang qua han la vi pham an toan thuc pham, nen nhan vien go hang khoi ke va xac nhan so THUC go (khong
can duyet, co ghi audit). Lo chuyen sang PULLED: khong con la ton ban duoc, khong tinh vao don dat hang.
Cai Store Manager duyet la BUT TOAN ghi huy (de xuat DISPOSE dung so thuc go, phan lech voi so ghi hao hut).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import audit
from app.clock import today
from app.models import Lot, Proposal


class PullError(Exception):
    pass


def sell_by(lot: Lot) -> date:
    return lot.sell_by


def _due_lots(db: Session, d: date) -> list[Lot]:
    """Lo dang ban ma ngay ban cuoi <= d. Loc so bo theo HSD (so ngay rut ke toi da vai tuan) roi loc dung."""
    rows = db.scalars(select(Lot).options(joinedload(Lot.product))
                      .where(Lot.status == "ACTIVE", Lot.qty_remaining > 0, Lot.expiry_date <= d + timedelta(days=60))
                      .order_by(Lot.expiry_date, Lot.id)).unique().all()
    return [l for l in rows if l.sell_by <= d]


def pull_list(db: Session, d: date | None = None) -> list[dict]:
    """Danh sach rut ke cuoi ngay. Co y KHONG kem so tren so: nguoi go ghi dung so thuc te go ra."""
    d = d or today()
    return [{"lot_id": l.id, "sku": l.product.sku, "name": l.product.name, "category": l.product.category,
             "expiry_date": l.expiry_date.isoformat(), "sell_by": l.sell_by.isoformat(),
             "overdue_days": (d - l.sell_by).days} for l in _due_lots(db, d)]


def confirm_pull(db: Session, entries: list[dict], actor: str) -> dict:
    """entries: [{lot_id, pulled_qty}]. Chi doi trang thai lo (khong doi gia tri ton tren so, khong ghi huy)."""
    if not entries:
        raise PullError("Chưa có lô nào được xác nhận.")
    t = today()
    done = []
    for e in entries:
        q = int(e["pulled_qty"])
        if q < 0:
            raise PullError("Số lượng gỡ không được âm.")
        lot = db.get(Lot, int(e["lot_id"]))
        if not lot or lot.status != "ACTIVE":
            raise PullError(f"Lô {e['lot_id']} không còn trên kệ (đã gỡ hoặc đã xử lý).")
        if lot.sell_by > t:
            raise PullError(f"Lô {lot.id} ({lot.product.name}) còn được bán đến {lot.sell_by:%d/%m/%Y}, chưa cần gỡ.")
        lot.status = "PULLED"
        lot.pulled_qty = q
        lot.pulled_date = t
        done.append({"lot_id": lot.id, "sku": lot.product.sku, "pulled_qty": q, "book_qty": lot.qty_remaining})
    audit.log(db, actor, "LOTS_PULLED", "lot", ",".join(str(x["lot_id"]) for x in done), {"lots": done})
    # De xuat ghi huy cu (lap theo so tren so truoc khi go) khong con dung so: thay bang de xuat moi
    ids = {x["lot_id"] for x in done}
    for p in db.scalars(select(Proposal).where(Proposal.type == "DISPOSE", Proposal.status.in_(["PENDING", "FAILED"]))):
        if any(it["lot_id"] in ids for it in p.payload.get("items", [])):
            p.status = "SUPERSEDED"
            p.decision_note = "Được thay bằng đề xuất mới theo số thực gỡ khỏi kệ."
            audit.log(db, actor, "PROPOSAL_SUPERSEDED", "proposal", p.id, {"reason": "pulled"})
    db.flush()
    return {"pulled": done}


def pulled_awaiting(db: Session) -> list[Lot]:
    return list(db.scalars(select(Lot).options(joinedload(Lot.product)).where(Lot.status == "PULLED")).unique())
