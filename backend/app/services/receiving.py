"""Nhan hang theo PO: BAT BUOC ghi HSD tung lo. Day la diem thu thap du lieu ma POS khong co."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import audit
from app.clock import now, today
from app.models import Lot, PurchaseOrder, StockMovement, User


class ReceiveError(Exception):
    pass


def receive_po(db: Session, po_id: int, lines: list[dict], user: User) -> dict:
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise ReceiveError("Không tìm thấy đơn hàng")
    if po.status != "SENT":
        raise ReceiveError(f"Đơn {po.code} đang ở trạng thái {po.status}, không nhận hàng được.")
    t = today()
    by_line = {int(l["line_id"]): l for l in lines}
    created = []
    for pl in po.lines:
        inp = by_line.get(pl.id, {})
        qty = int(inp.get("received_qty", pl.qty))
        if qty < 0:
            raise ReceiveError("Số lượng nhận không được âm")
        pl.received_qty = qty
        if qty == 0:
            continue
        exp_raw = inp.get("expiry_date")
        if not exp_raw:
            raise ReceiveError(f"Thiếu hạn sử dụng cho {pl.product.sku} {pl.product.name}. "
                               "Mỗi lô nhận vào phải có HSD để quản lý FEFO.")
        exp = date.fromisoformat(exp_raw) if isinstance(exp_raw, str) else exp_raw
        if exp < t:
            raise ReceiveError(f"HSD {exp} của {pl.product.sku} đã qua. Không nhận hàng hết hạn.")
        if (exp - t).days + 1 < max(1, pl.product.shelf_life_days // 2) and pl.product.shelf_life_days > 3:
            # Canh bao, khong chan: hang giao da qua nua vong doi
            audit.log(db, user.username, "RECEIVE_SHORT_DATED", "po_line", pl.id,
                      {"sku": pl.product.sku, "expiry": exp.isoformat()})
        lot = Lot(product_id=pl.product_id, qty_received=qty, qty_remaining=qty, received_date=t, expiry_date=exp,
                  unit_cost=pl.unit_cost, po_line_id=pl.id, status="ACTIVE")
        db.add(lot)
        db.flush()
        db.add(StockMovement(product_id=pl.product_id, lot_id=lot.id, date=t, type="IN", qty=qty,
                             unit_cost=pl.unit_cost, value=qty * pl.unit_cost, ref=po.code))
        created.append({"lot_id": lot.id, "sku": pl.product.sku, "qty": qty, "expiry_date": exp.isoformat()})
    po.status = "RECEIVED"
    po.received_at = now().replace(tzinfo=None)
    audit.log(db, user.username, "PO_RECEIVED", "purchase_order", po.id, {"code": po.code, "lots": created})
    db.commit()
    return {"code": po.code, "lots": created}


def default_expiry(shelf_life_days: int, received: date | None = None) -> date:
    return (received or today()) + timedelta(days=shelf_life_days - 1)
