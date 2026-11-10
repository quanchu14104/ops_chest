"""Vong doi phieu tra NCC: REQUESTED -> CONFIRMED -> PICKED_UP -> CREDITED, hoac REFUSED.

Tien chi co khi doi tac xac nhan. Khi SM duyet de xuat tra hang, phan hang tra duoc TACH thanh lo
RETURN_PENDING (khong ban, khong tinh ton) va email gui NCC, nhung CHUA ghi tien. Chi khi NCC thuc lay hang
va SM nhap so thuc nhan, he thong moi ghi RETURN (tien hoan) hoac nhap lo hang doi (gia von 0, voi
thoa thuan doi hang). NCC tu choi thi lo quay lai ban va he thong xet lai phuong an giam gia.
Cac thao tac o day la cua Store Manager (co ghi audit), khong phai cua agent.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.clock import today
from app.models import Lot, StockMovement, SupplierReturn, User


class ReturnError(Exception):
    pass


MODE_LABEL = {"CREDIT": "hoàn tiền / trừ vào đơn sau", "EXCHANGE": "đổi hàng mới (đổi date)"}
STATUS_LABEL = {"REQUESTED": "Đã gửi đề nghị", "CONFIRMED": "NCC đã xác nhận", "PICKED_UP": "NCC đã lấy hàng",
                "CREDITED": "Đã nhận tiền/hàng đổi", "REFUSED": "NCC từ chối"}


def split_for_return(db: Session, lot: Lot, qty: int) -> Lot:
    """Tach `qty` don vi khoi lo dang ban thanh lo cho tra. Lo goc giu phan con lai."""
    if qty <= 0 or qty > lot.qty_remaining:
        raise ReturnError(f"Lô {lot.id} chỉ còn {lot.qty_remaining}, không tách được {qty} để trả.")
    if qty == lot.qty_remaining:
        lot.status = "RETURN_PENDING"
        return lot
    lot.qty_remaining -= qty
    part = Lot(product_id=lot.product_id, qty_received=qty, qty_remaining=qty, received_date=lot.received_date,
               expiry_date=lot.expiry_date, unit_cost=lot.unit_cost, markdown_pct=lot.markdown_pct,
               po_line_id=lot.po_line_id, status="RETURN_PENDING")
    db.add(part)
    db.flush()
    return part


def _get(db: Session, rid: int, allowed: tuple[str, ...]) -> SupplierReturn:
    r = db.get(SupplierReturn, rid)
    if not r:
        raise ReturnError("Không tìm thấy phiếu trả hàng")
    if r.status not in allowed:
        raise ReturnError(f"Phiếu {r.code} đang ở trạng thái {STATUS_LABEL.get(r.status, r.status)}, không thao tác được.")
    return r


def confirm(db: Session, rid: int, user: User) -> SupplierReturn:
    r = _get(db, rid, ("REQUESTED",))
    r.status, r.confirmed_date = "CONFIRMED", today()
    audit.log(db, user.username, "RETURN_CONFIRMED", "supplier_return", r.id, {"code": r.code})
    return r


def pick_up(db: Session, rid: int, picked: dict[int, int], user: User) -> SupplierReturn:
    """NCC da lay hang. picked: {lot_id: so NCC thuc nhan}. Day moi la luc ghi RETURN / nhap hang doi.
    Phan NCC khong nhan quay lai ban."""
    r = _get(db, rid, ("REQUESTED", "CONFIRMED"))
    t = today()
    items, credit, back = [], 0, []
    for it in r.items:
        lot = db.get(Lot, it["lot_id"])
        if not lot or lot.status != "RETURN_PENDING":
            raise ReturnError(f"Lô {it['lot_id']} không còn ở trạng thái chờ trả.")
        q = int(picked.get(it["lot_id"], picked.get(str(it["lot_id"]), it["qty"])))
        if not 0 <= q <= lot.qty_remaining:
            raise ReturnError(f"Lô {lot.id}: số NCC nhận phải từ 0 đến {lot.qty_remaining}.")
        if q:
            c = int(round(q * lot.unit_cost * r.credit_pct)) if r.mode == "CREDIT" else 0
            credit += c
            db.add(StockMovement(product_id=lot.product_id, lot_id=lot.id, date=t, type="RETURN", qty=q,
                                 unit_cost=lot.unit_cost, value=c, ref=r.code,
                                 note=f"Trả NCC ({MODE_LABEL[r.mode]})"))
            if r.mode == "EXCHANGE":  # hang doi: lo moi gia von 0, HSD moi theo vong doi chuan
                prod = lot.product
                new = Lot(product_id=lot.product_id, qty_received=q, qty_remaining=q, received_date=t,
                          expiry_date=t + timedelta(days=prod.shelf_life_days - 1), unit_cost=0, status="ACTIVE")
                db.add(new)
                db.flush()
                db.add(StockMovement(product_id=lot.product_id, lot_id=new.id, date=t, type="IN", qty=q, unit_cost=0,
                                     value=0, ref=r.code, note="Hàng đổi từ phiếu trả NCC"))
        rest = lot.qty_remaining - q
        lot.qty_remaining = rest
        lot.status = "ACTIVE" if rest > 0 else "RETURNED"
        if rest:
            back.append(lot.id)
        items.append({**it, "picked_qty": q})
    r.items = items
    r.picked_up_date = t
    r.credit_value = credit
    # Doi hang xong la xong; hoan tien con cho NCC tra/tru vao don sau
    r.status = "CREDITED" if r.mode == "EXCHANGE" else "PICKED_UP"
    if r.mode == "EXCHANGE":
        r.credited_date = t
    audit.log(db, user.username, "RETURN_PICKED_UP", "supplier_return", r.id,
              {"code": r.code, "credit": credit, "back_on_shelf": back})
    return r


def mark_credited(db: Session, rid: int, user: User, amount: int | None = None) -> SupplierReturn:
    r = _get(db, rid, ("PICKED_UP",))
    r.status, r.credited_date = "CREDITED", today()
    if amount is not None and int(amount) != r.credit_value:
        r.note = f"NCC hoàn {int(amount):,}đ, khác số ghi nhận {r.credit_value:,}đ".replace(",", ".")
    audit.log(db, user.username, "RETURN_CREDITED", "supplier_return", r.id, {"code": r.code, "amount": amount})
    return r


def refuse(db: Session, rid: int, reason: str, user: User) -> tuple[SupplierReturn, list[int]]:
    """NCC tu choi: lo quay lai ban (tra ve ACTIVE). Tra ve danh sach lo de xet lai giam gia."""
    if not reason or not reason.strip():
        raise ReturnError("Cần ghi lý do NCC từ chối.")
    r = _get(db, rid, ("REQUESTED", "CONFIRMED"))
    lots = []
    for it in r.items:
        lot = db.get(Lot, it["lot_id"])
        if lot and lot.status == "RETURN_PENDING":
            lot.status = "ACTIVE"
            lots.append(lot.id)
    r.status, r.note = "REFUSED", reason.strip()
    audit.log(db, user.username, "RETURN_REFUSED", "supplier_return", r.id, {"code": r.code, "reason": reason.strip()})
    return r, lots


def overdue(db: Session, days: int = 5, d: date | None = None) -> list[SupplierReturn]:
    """Phieu da gui ma NCC chua lay hang sau `days` ngay."""
    d = d or today()
    return list(db.scalars(select(SupplierReturn).where(SupplierReturn.status.in_(["REQUESTED", "CONFIRMED"]),
                                                        SupplierReturn.requested_date <= d - timedelta(days=days))))


def view(r: SupplierReturn) -> dict:
    return {"id": r.id, "code": r.code, "supplier": r.supplier.name, "status": r.status,
            "status_label": STATUS_LABEL.get(r.status, r.status), "mode": r.mode, "mode_label": MODE_LABEL[r.mode],
            "credit_pct": r.credit_pct, "items": r.items, "est_credit": r.est_credit, "credit_value": r.credit_value,
            "requested_date": r.requested_date.isoformat(), "proposal_id": r.proposal_id,
            "confirmed_date": r.confirmed_date.isoformat() if r.confirmed_date else None,
            "picked_up_date": r.picked_up_date.isoformat() if r.picked_up_date else None,
            "credited_date": r.credited_date.isoformat() if r.credited_date else None, "note": r.note,
            "days_open": (today() - r.requested_date).days}
