"""Thuc thi de xuat DA DUYET. Chi duoc goi tu proposals.service.approve.

Thu tu: ghi DB truoc (flush), tac dung phu ben ngoai (gui email) CUOI CUNG. Neu email loi -> exception ->
service rollback toan bo, de xuat chuyen FAILED, SM co the duyet lai (thu lai).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import now, today
from app.config import settings
from app.models import (DemandHypothesis, Lot, OrderAdjustment, POLine, Product, Proposal, PurchaseOrder,
                        StockMovement, Supplier, User)
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
    done, kept = [], []
    for it in p.payload["items"]:
        if it.get("include") is False:
            continue
        lot = _active_lot(db, it["lot_id"])
        pct = float(it["markdown_pct"])
        if not 0 < pct < 0.95:
            raise ExecutionError(f"Mức giảm {pct} không hợp lệ cho lô {lot.id}.")
        if pct <= lot.markdown_pct:  # tem da dan: khong tang gia tro lai
            kept.append({"lot_id": lot.id, "sku": it["sku"], "markdown_pct": lot.markdown_pct})
            continue
        lot.markdown_pct = pct
        done.append({"lot_id": lot.id, "sku": it["sku"], "markdown_pct": pct, "timing": it.get("timing")})
    if not done:
        raise ExecutionError("Không còn lô nào cần giảm thêm: các lô được chọn đã ở mức giảm bằng hoặc sâu hơn.")
    return {"lots_marked_down": done, "kept_higher": kept,
            "instruction": "In tem giảm giá và dán lên sản phẩm của các lô trên."}


def _return(db: Session, p: Proposal, user: User) -> dict:
    pl = p.payload
    t = today()
    credit_pct = float(pl["credit_pct"])
    if db.get(Supplier, pl["supplier_id"]).agreement_on(t) is None:
        raise ExecutionError(f"Thỏa thuận với {pl['supplier_name']} đã hết hiệu lực, không còn căn cứ để trả hàng.")
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


def _demand_hypothesis(db: Session, p: Proposal, user: User) -> dict:
    from app.services import hypotheses as H

    pl = p.payload
    start, end = date.fromisoformat(pl["start_date"]), date.fromisoformat(pl["end_date"])
    try:
        H.validate(db, float(pl["factor"]), start, end, pl["reason"], pl["category"], pl["sku"])
    except H.HypothesisError as e:
        raise ExecutionError(str(e)) from e
    row = DemandHypothesis(category=pl["category"], sku=pl["sku"], factor=float(pl["factor"]), start_date=start,
                           end_date=end, reason=pl["reason"], status="ACTIVE", baseline_total=float(pl["baseline_total"]),
                           proposal_id=p.id, created_by=user.username, created_at=now().replace(tzinfo=None))
    db.add(row)
    db.flush()
    return {"hypothesis_id": row.id, "note": f"Dự báo {pl['scope']} đã áp dụng ×{pl['factor']:g} trong khoảng ngày đã nêu."}


def _order_adjust(db: Session, p: Proposal, user: User) -> dict:
    pl = p.payload
    if db.scalar(select(OrderAdjustment.id).where(OrderAdjustment.category == pl["category"], OrderAdjustment.active.is_(True))):
        raise ExecutionError(f"Nhóm {pl['category']} đã có hệ số đang chạy.")
    row = OrderAdjustment(category=pl["category"], factor=float(pl["factor"]), active=True, reason=pl["reason"],
                          proposal_id=p.id, created_by=user.username, created_at=now().replace(tzinfo=None))
    db.add(row)
    db.flush()
    return {"adjustment_id": row.id, "note": f"Số lượng đề xuất nhóm {pl['category']} sẽ nhân ×{pl['factor']:g}. Có thể tắt ở trang Tổng quan."}


def _stock_adjust(db: Session, p: Proposal, user: User) -> dict:
    """Thieu: tru tu lo gan het han truoc (khong biet mat o lo nao). Du: cong vao lo moi nhat."""
    t = today()
    ref = f"proposal:{p.id}"
    total = 0
    for it in p.payload["items"]:
        lots = list(db.scalars(select(Lot).where(Lot.product_id == it["product_id"], Lot.status == "ACTIVE", Lot.qty_remaining > 0)
                               .order_by(Lot.expiry_date, Lot.id)))
        if sum(l.qty_remaining for l in lots) != it["system_qty"]:
            raise ExecutionError(f"Tồn của {it['sku']} đã thay đổi sau khi đếm, hãy đếm lại.")
        remaining = int(it["diff"])
        if remaining > 0:
            lot = lots[-1] if lots else None
            if lot is None:
                prod = db.get(Product, it["product_id"])
                lot = Lot(product_id=prod.id, qty_received=0, qty_remaining=0, received_date=t,
                          expiry_date=t + timedelta(days=prod.shelf_life_days - 1), unit_cost=prod.unit_cost, status="ACTIVE")
                db.add(lot)
                db.flush()
            lot.qty_remaining += remaining
            v = remaining * lot.unit_cost
            db.add(StockMovement(product_id=it["product_id"], lot_id=lot.id, date=t, type="ADJUST", qty=remaining,
                                 unit_cost=lot.unit_cost, value=v, ref=ref, note="Kiểm kê: dư so với sổ"))
            total += v
            continue
        for lot in lots:
            if remaining >= 0:
                break
            q = min(lot.qty_remaining, -remaining)
            lot.qty_remaining -= q
            remaining += q
            if lot.qty_remaining == 0:
                lot.status = "ADJUSTED"
            v = -q * lot.unit_cost
            db.add(StockMovement(product_id=it["product_id"], lot_id=lot.id, date=t, type="ADJUST", qty=-q,
                                 unit_cost=lot.unit_cost, value=v, ref=ref, note="Kiểm kê: thiếu so với sổ"))
            total += v
    return {"items": len(p.payload["items"]), "net_value": total}


EXECUTORS = {
    "STOCK_ADJUST": _stock_adjust,
    "PURCHASE_ORDER": _purchase_order,
    "MARKDOWN": _markdown,
    "RETURN": _return,
    "DISPOSE": _dispose,
    "DELIST": _delist,
    "DEMAND_HYPOTHESIS": _demand_hypothesis,
    "ORDER_ADJUST": _order_adjust,
}


def execute(db: Session, p: Proposal, user: User) -> dict:
    return EXECUTORS[p.type](db, p, user)
