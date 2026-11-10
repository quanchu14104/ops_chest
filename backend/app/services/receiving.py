"""Nhan hang theo PO: BAT BUOC ghi HSD tung lo. Day la diem thu thap du lieu ma POS khong co."""
from __future__ import annotations

import math
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.clock import now, today
from app.config import settings
from app.fmt import vnd
from app.models import Lot, PurchaseOrder, StockMovement, User


REJECT_REASONS = {
    "DAMAGED": "Móp, vỡ, rách bao bì",
    "SHORT_DATED": "Date ngắn",
    "WRONG_ITEM": "Sai hàng",
    "OTHER": "Lý do khác",
}


class ReceiveError(Exception):
    pass


def min_remaining_days(shelf_life_days: int) -> int:
    """So ngay con han toi thieu de nhan (chuan nhan hang = ty le vong doi con lai, mac dinh 2/3)."""
    return max(1, math.ceil(shelf_life_days * settings.receive_min_remaining_life_pct))


def over_tolerance(qty: int, pack_size: int) -> int:
    """Giao du toi da bao nhieu thi nhan vien tu nhan; vuot qua (10% hoac mot quy cach, lay muc lon hon) can SM."""
    return max(int(qty * settings.receive_over_tolerance_pct), max(1, pack_size))


def _lots_of(inp: dict, default_qty: int) -> list[tuple[int, object]]:
    """Mot dong PO co the giao nhieu HSD: `lots` = [{qty, expiry_date}]. Dang cu (received_qty + expiry_date)
    van duoc chap nhan nhu mot lo."""
    if inp.get("lots"):
        return [(int(x["qty"]), x.get("expiry_date")) for x in inp["lots"]]
    return [(int(inp.get("received_qty", default_qty)), inp.get("expiry_date"))]


def receive_po(db: Session, po_id: int, lines: list[dict], user: User) -> dict:
    """Nhan hang. Nhan vien tu xac nhan; ba truong hop can Store Manager (nguoi nhan la manager va tick xac nhan):
    lo date ngan duoi chuan, giao du vuot nguong, va (chi canh bao) gia hoa don khac PO."""
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise ReceiveError("Không tìm thấy đơn hàng")
    if po.status != "SENT":
        raise ReceiveError(f"Đơn {po.code} đang ở trạng thái {po.status}, không nhận hàng được.")
    t = today()
    is_manager = getattr(user, "role", None) == "manager"
    by_line = {int(l["line_id"]): l for l in lines}
    created, warnings, shortages = [], [], []
    for pl in po.lines:
        inp = by_line.get(pl.id, {})
        prod = pl.product
        pairs = [(q, e) for q, e in _lots_of(inp, pl.qty)]
        if any(q < 0 for q, _ in pairs):
            raise ReceiveError("Số lượng nhận không được âm")
        qty = sum(q for q, _ in pairs)
        rejected = int(inp.get("rejected_qty") or 0)
        if rejected < 0:
            raise ReceiveError("Số lượng từ chối không được âm")
        reason = (inp.get("reject_reason") or "").upper() or None
        if rejected and reason not in REJECT_REASONS:
            raise ReceiveError(f"Cần lý do từ chối hợp lệ cho {prod.sku} {prod.name}.")
        over = qty - pl.qty
        if over > over_tolerance(pl.qty, prod.pack_size):
            if not (is_manager and inp.get("accept_over")):
                raise ReceiveError(f"{prod.sku} {prod.name}: nhận {qty} so với đặt {pl.qty}, dư quá ngưỡng. "
                                   "Cần Store Manager xác nhận nhận dư, hoặc từ chối phần dư.")
            warnings.append(f"{prod.sku}: Store Manager xác nhận nhận dư {over} so với đơn.")
        cost = pl.unit_cost
        if inp.get("actual_unit_cost") not in (None, ""):
            cost = int(inp["actual_unit_cost"])
            if cost < 0:
                raise ReceiveError("Giá trên hóa đơn không được âm")
            if cost != pl.unit_cost:
                warnings.append(f"{prod.sku}: giá hóa đơn {vnd(cost)} khác giá trên đơn {vnd(pl.unit_cost)} "
                                f"({(cost - pl.unit_cost) / max(pl.unit_cost, 1):+.0%}).")
                pl.actual_unit_cost = cost
        pl.received_qty = qty
        pl.rejected_qty = rejected or None
        pl.reject_reason = reason if rejected else None
        pl.short_qty = max(0, pl.qty - qty - rejected) or None
        if pl.short_qty:
            shortages.append({"sku": prod.sku, "name": prod.name, "ordered": pl.qty, "short": pl.short_qty})
        for q, exp_raw in pairs:
            if q == 0:
                continue
            if not exp_raw:
                raise ReceiveError(f"Thiếu hạn sử dụng cho {prod.sku} {prod.name}. "
                                   "Mỗi lô nhận vào phải có HSD để quản lý FEFO.")
            exp = date.fromisoformat(exp_raw) if isinstance(exp_raw, str) else exp_raw
            if exp < t:
                raise ReceiveError(f"HSD {exp} của {prod.sku} đã qua. Không nhận hàng hết hạn.")
            need = min_remaining_days(prod.shelf_life_days)
            left = (exp - t).days + 1
            if left < need:
                if not (is_manager and inp.get("accept_short_dated")):
                    raise ReceiveError(
                        f"{prod.sku} {prod.name}: HSD {exp:%d/%m/%Y} chỉ còn {left}/{prod.shelf_life_days} ngày, dưới "
                        f"chuẩn nhận hàng ({need} ngày). Mặc định từ chối (ghi vào số từ chối, lý do date ngắn); "
                        "muốn nhận phải có Store Manager xác nhận.")
                warnings.append(f"{prod.sku}: Store Manager xác nhận nhận lô date ngắn (HSD {exp:%d/%m/%Y}).")
                audit.log(db, user.username, "RECEIVE_SHORT_DATED", "po_line", pl.id,
                          {"sku": prod.sku, "expiry": exp.isoformat(), "days_left": left, "standard": need})
            lot = Lot(product_id=pl.product_id, qty_received=q, qty_remaining=q, received_date=t, expiry_date=exp,
                      unit_cost=cost, po_line_id=pl.id, status="ACTIVE")
            db.add(lot)
            db.flush()
            db.add(StockMovement(product_id=pl.product_id, lot_id=lot.id, date=t, type="IN", qty=q,
                                 unit_cost=cost, value=q * cost, ref=po.code))
            created.append({"lot_id": lot.id, "sku": prod.sku, "qty": q, "expiry_date": exp.isoformat()})
    po.status = "RECEIVED"
    po.received_at = now().replace(tzinfo=None)
    audit.log(db, user.username, "PO_RECEIVED", "purchase_order", po.id,
              {"code": po.code, "lots": created, "shortages": shortages, "warnings": warnings})
    db.commit()
    return {"code": po.code, "lots": created, "shortages": shortages, "warnings": warnings}


def recent_shortages(db: Session, days: int = 7) -> list[dict]:
    """Don nhan trong `days` ngay qua bi giao thieu (cho ban tin va diem NCC)."""
    since = now().replace(tzinfo=None) - timedelta(days=days)
    out = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "RECEIVED", PurchaseOrder.received_at >= since)):
        short = [l for l in po.lines if l.short_qty]
        if short:
            out.append({"code": po.code, "supplier": po.supplier.name, "lines": len(short),
                        "units": sum(l.short_qty for l in short)})
    return out


def cancel_po(db: Session, po_id: int, reason: str, user: User) -> dict:
    """Don khong con giao nua: bo khoi hang dang ve de lan dat sau tinh dung. Chi doi trang thai, khong gui email."""
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise ReceiveError("Không tìm thấy đơn hàng")
    if po.status != "SENT":
        raise ReceiveError(f"Đơn {po.code} đang ở trạng thái {po.status}, không huỷ được.")
    if not reason or not reason.strip():
        raise ReceiveError("Cần ghi lý do huỷ đơn.")
    po.status = "CANCELLED"
    audit.log(db, user.username, "PO_CANCELLED", "purchase_order", po.id, {"code": po.code, "reason": reason.strip()})
    db.commit()
    return {"code": po.code, "status": po.status}


def default_expiry(shelf_life_days: int, received: date | None = None) -> date:
    return (received or today()) + timedelta(days=shelf_life_days - 1)
