"""Thuc thi de xuat DA DUYET. Chi duoc goi tu proposals.service.approve.

Thu tu: ghi DB truoc (flush), tac dung phu ben ngoai (gui email) CUOI CUNG. Neu email loi -> exception ->
service rollback toan bo, de xuat chuyen FAILED, SM co the duyet lai (thu lai).
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import now, today
from app.config import settings
from app.models import Lot, POLine, Product, Proposal, PurchaseOrder, StockMovement, Supplier, User
from app.notify import email, pdf


class ExecutionError(Exception):
    pass


def _po_code(db: Session) -> str:
    t = today()
    n = db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.order_date == t)) or 0
    while True:
        n += 1
        code = f"PO{t:%y%m%d}-{n:03d}"
        if not db.scalar(select(PurchaseOrder.id).where(PurchaseOrder.code == code)):
            return code


def _purchase_order(db: Session, p: Proposal, user: User) -> dict:
    pl = p.payload
    lines = [l for l in pl["lines"] if int(l["qty"]) > 0]
    if not lines:
        raise ExecutionError("Đơn không còn dòng hàng nào có số lượng > 0.")
    sup = db.get(Supplier, pl["supplier_id"])
    t = today()
    expected = t + timedelta(days=sup.lead_time_days)
    total = sum(int(l["qty"]) * int(l["unit_cost"]) for l in lines)
    code = _po_code(db)
    po = PurchaseOrder(code=code, supplier_id=sup.id, proposal_id=p.id, status="SENT", order_date=t,
                       expected_date=expected, total_value=total)
    for l in lines:
        po.lines.append(POLine(product_id=l["product_id"], qty=int(l["qty"]), unit_cost=int(l["unit_cost"])))
    db.add(po)
    db.flush()
    pdf_bytes = pdf.purchase_order_pdf(
        code, {"name": sup.name, "code": sup.code, "email": sup.email}, t.strftime("%d/%m/%Y"),
        expected.strftime("%d/%m/%Y"), lines, total, user.full_name, pl.get("note") or None)
    out = Path(settings.pdf_output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{code}.pdf"
    path.write_bytes(pdf_bytes)
    po.pdf_path = str(path)
    html = email.render("po_email.html", supplier_name=sup.name, code=code, expected_date=expected.strftime("%d/%m/%Y"),
                        lines=lines, total=total, note=pl.get("note"), approved_by=user.full_name)
    msg_id = email.send_email(sup.email, f"[{settings.store_name}] Đơn đặt hàng {code}", html,
                              [(f"{code}.pdf", pdf_bytes, "application/pdf")])
    po.sent_at = now().replace(tzinfo=None)
    return {"purchase_order_id": po.id, "code": code, "total_value": total, "lines": len(lines),
            "email_to": sup.email, "message_id": msg_id, "expected_date": expected.isoformat()}


def _active_lot(db: Session, lot_id: int) -> Lot:
    lot = db.get(Lot, lot_id)
    if not lot or lot.status != "ACTIVE" or lot.qty_remaining <= 0:
        raise ExecutionError(f"Lô {lot_id} không còn hàng hoặc đã được xử lý.")
    return lot


def _markdown(db: Session, p: Proposal, user: User) -> dict:
    done = []
    for it in p.payload["items"]:
        if it.get("include") is False:
            continue
        lot = _active_lot(db, it["lot_id"])
        pct = float(it["markdown_pct"])
        if not 0 < pct < 0.95:
            raise ExecutionError(f"Mức giảm {pct} không hợp lệ cho lô {lot.id}.")
        lot.markdown_pct = pct
        done.append({"lot_id": lot.id, "sku": it["sku"], "markdown_pct": pct, "timing": it.get("timing")})
    if not done:
        raise ExecutionError("Không còn lô nào được chọn để giảm giá.")
    return {"lots_marked_down": done, "instruction": "In tem giảm giá và dán lên sản phẩm của các lô trên."}


def _return(db: Session, p: Proposal, user: User) -> dict:
    pl = p.payload
    t = today()
    credit_pct = float(pl["credit_pct"])
    items, credit = [], 0
    for it in pl["items"]:
        q = int(it["qty"])
        if q <= 0:
            continue
        lot = _active_lot(db, it["lot_id"])
        if q > lot.qty_remaining:
            raise ExecutionError(f"Lô {lot.id} chỉ còn {lot.qty_remaining}, không trả được {q}.")
        lot.qty_remaining -= q
        if lot.qty_remaining == 0:
            lot.status = "RETURNED"
        c = int(round(q * lot.unit_cost * credit_pct))
        credit += c
        db.add(StockMovement(product_id=lot.product_id, lot_id=lot.id, date=t, type="RETURN", qty=q,
                             unit_cost=lot.unit_cost, value=c, ref=f"proposal:{p.id}", note="Trả NCC hàng cận date"))
        items.append({**it, "qty": q})
    if not items:
        raise ExecutionError("Không còn dòng trả hàng nào có số lượng > 0.")
    code = f"RT{t:%y%m%d}-{p.id}"
    html = email.render("return_email.html", supplier_name=pl["supplier_name"], code=code, items=items,
                        credit=credit, approved_by=user.full_name)
    msg_id = email.send_email(pl["supplier_email"], f"[{settings.store_name}] Đề nghị trả hàng cận hạn {code}", html)
    return {"code": code, "credit": credit, "items": len(items), "email_to": pl["supplier_email"], "message_id": msg_id}


def _dispose(db: Session, p: Proposal, user: User) -> dict:
    t = today()
    total, n = 0, 0
    for it in p.payload["items"]:
        q = int(it["qty"])
        if q <= 0:
            continue
        lot = _active_lot(db, it["lot_id"])
        q = min(q, lot.qty_remaining)
        lot.qty_remaining -= q
        if lot.qty_remaining == 0:
            lot.status = "WASTED"
        v = q * lot.unit_cost
        total += v
        n += 1
        db.add(StockMovement(product_id=lot.product_id, lot_id=lot.id, date=t, type="WASTE", qty=q,
                             unit_cost=lot.unit_cost, value=v, ref=f"proposal:{p.id}", note="Hủy hàng quá hạn"))
    return {"lots_disposed": n, "waste_cost": total}


def _delist(db: Session, p: Proposal, user: User) -> dict:
    prod = db.get(Product, p.payload["product_id"])
    if prod.status != "ACTIVE":
        raise ExecutionError(f"{prod.sku} đã ngừng nhập trước đó.")
    prod.status = "DELISTED"
    return {"sku": prod.sku, "status": "DELISTED",
            "note": "Không còn được đưa vào đề xuất đặt hàng. Hàng tồn tiếp tục bán đến hết."}


EXECUTORS = {
    "PURCHASE_ORDER": _purchase_order,
    "MARKDOWN": _markdown,
    "RETURN": _return,
    "DISPOSE": _dispose,
    "DELIST": _delist,
}


def execute(db: Session, p: Proposal, user: User) -> dict:
    return EXECUTORS[p.type](db, p, user)
