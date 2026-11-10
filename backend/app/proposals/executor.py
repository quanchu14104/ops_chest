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
from app.fmt import vnd
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
    expected, _ = sup.schedule(t)  # theo lich giao va lich nghi cua NCC
    total = sum(int(l["qty"]) * int(l["unit_cost"]) for l in lines)
    if sup.min_order_value and total < sup.min_order_value and not pl.get("min_order_ack"):
        raise ExecutionError(f"Đơn {vnd(total)} dưới giá trị tối thiểu {vnd(sup.min_order_value)} của {sup.name}. "
                             "Hãy bù đơn, hoãn, hoặc đánh dấu đã thỏa thuận với NCC rồi duyệt lại.")
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
    from app.services import policies

    pol = policies.by_category(db)
    done, kept = [], []
    for it in p.payload["items"]:
        if it.get("include") is False:
            continue
        lot = _active_lot(db, it["lot_id"])
        pct = float(it["markdown_pct"])
        if not 0 < pct < 0.95:
            raise ExecutionError(f"Mức giảm {pct} không hợp lệ cho lô {lot.id}.")
        try:  # rang buoc theo nhom hang kiem tra lai luc thuc thi (cau hinh co the doi sau khi tao de xuat)
            policies.check_markdown(pol, lot.product.category, pct)
        except policies.MarkdownPolicyError as e:
            raise ExecutionError(str(e)) from e
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
    """Duyet = tach hang ra cho tra + gui email. CHUA ghi tien: tien (hoac hang doi) chi ghi khi NCC lay hang."""
    from app.models import SupplierReturn
    from app.services.returns import MODE_LABEL, ReturnError, split_for_return

    pl = p.payload
    t = today()
    sup = db.get(Supplier, pl["supplier_id"])
    agr = sup.agreement_on(t)
    if agr is None:
        raise ExecutionError(f"Thỏa thuận với {pl['supplier_name']} đã hết hiệu lực, không còn căn cứ để trả hàng.")
    credit_pct = float(pl["credit_pct"])
    mode = pl.get("return_mode") or agr.return_mode or "CREDIT"
    items, est = [], 0
    for it in pl["items"]:
        q = int(it["qty"])
        if q <= 0:
            continue
        lot = _active_lot(db, it["lot_id"])
        try:
            part = split_for_return(db, lot, q)
        except ReturnError as e:
            raise ExecutionError(str(e)) from e
        est += int(round(q * lot.unit_cost * credit_pct))
        items.append({"lot_id": part.id, "source_lot_id": lot.id, "sku": it["sku"], "name": it["name"], "qty": q,
                      "unit_cost": lot.unit_cost, "expiry_date": it["expiry_date"]})
    if not items:
        raise ExecutionError("Không còn dòng trả hàng nào có số lượng > 0.")
    code = f"RT{t:%y%m%d}-{p.id}"
    r = SupplierReturn(code=code, supplier_id=sup.id, proposal_id=p.id, status="REQUESTED", mode=mode,
                       credit_pct=credit_pct, items=items, est_credit=est if mode == "CREDIT" else 0, requested_date=t)
    db.add(r)
    db.flush()
    html = email.render("return_email.html", supplier_name=pl["supplier_name"], code=code, items=items,
                        credit=est, mode=mode, mode_label=MODE_LABEL[mode], approved_by=user.full_name)
    msg_id = email.send_email(pl["supplier_email"], f"[{settings.store_name}] Đề nghị trả hàng cận hạn {code}", html)
    return {"code": code, "return_id": r.id, "mode": mode, "est_credit": r.est_credit, "items": len(items),
            "email_to": pl["supplier_email"], "message_id": msg_id,
            "note": "Hàng đã tách khỏi kệ chờ NCC lấy. Tiền hoàn/hàng đổi chỉ ghi khi NCC lấy hàng."}


def _dispose(db: Session, p: Proposal, user: User) -> dict:
    """Dong `close_lot` (het han): ghi huy so thuc go, phan lech voi so ghi hao hut, lo dong han.
    Dong khac (vo, hong...): chi tru dung so luong bao huy, lo con lai van ban tiep."""
    t = today()
    ref = f"proposal:{p.id}"
    total, shrink, n = 0, 0, 0
    by_reason: dict[str, int] = {}
    for it in p.payload["items"]:
        q = int(it["qty"])
        reason = it.get("reason") or "EXPIRED"
        if it.get("close_lot"):
            lot = db.get(Lot, it["lot_id"])
            if not lot or lot.status not in ("ACTIVE", "PULLED"):
                raise ExecutionError(f"Lô {it['lot_id']} đã được xử lý trước đó.")
            if q < 0:
                raise ExecutionError("Số lượng hủy không được âm.")
            book = lot.qty_remaining
            if q != book:  # chenh lech giua so tren so va so thuc te: hao hut (hoac du so)
                v = (q - book) * lot.unit_cost
                db.add(StockMovement(product_id=lot.product_id, lot_id=lot.id, date=t, type="ADJUST", qty=q - book,
                                     unit_cost=lot.unit_cost, value=v, ref=ref, reason="SHRINK",
                                     note="Chênh lệch giữa sổ và số thực gỡ khỏi kệ"))
                shrink += v
            lot.qty_remaining = 0
            lot.status = "WASTED"
        else:
            if q <= 0:
                continue
            lot = _active_lot(db, it["lot_id"])
            if q > lot.qty_remaining:
                raise ExecutionError(f"Lô {lot.id} chỉ còn {lot.qty_remaining}, không hủy được {q}.")
            lot.qty_remaining -= q
            if lot.qty_remaining == 0:
                lot.status = "WASTED"
        if q > 0:
            v = q * lot.unit_cost
            total += v
            by_reason[reason] = by_reason.get(reason, 0) + v
            db.add(StockMovement(product_id=lot.product_id, lot_id=lot.id, date=t, type="WASTE", qty=q,
                                 unit_cost=lot.unit_cost, value=v, ref=ref, reason=reason,
                                 note=it.get("reason_label") or "Hủy hàng quá hạn"))
        n += 1
    if not n:
        raise ExecutionError("Không còn dòng hủy nào có số lượng > 0.")
    return {"lots_disposed": n, "waste_cost": total, "shrink_value": -shrink, "by_reason": by_reason}


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


def _lot_adjust(db: Session, p: Proposal) -> dict:
    """Kiem date: sua so theo tung HSD. Lo co HSD do da dong (vd ban het tren so) thi mo lai; chua tung co
    thi tao lo moi. So tren so cua HSD da doi tu luc dem thi that bai va phai dem lai."""
    t = today()
    ref = f"proposal:{p.id}"
    total = 0
    for it in p.payload["items"]:
        exp = date.fromisoformat(it["expiry_date"])
        lots = list(db.scalars(select(Lot).where(Lot.product_id == it["product_id"], Lot.expiry_date == exp,
                                                 Lot.status == "ACTIVE", Lot.qty_remaining > 0).order_by(Lot.id)))
        if sum(l.qty_remaining for l in lots) != it["system_qty"]:
            raise ExecutionError(f"Tồn lô HSD {exp:%d/%m/%Y} của {it['sku']} đã thay đổi sau khi đếm, hãy đếm lại.")
        diff = int(it["diff"])
        if diff > 0:
            lot = lots[-1] if lots else db.scalar(
                select(Lot).where(Lot.product_id == it["product_id"], Lot.expiry_date == exp,
                                  Lot.status.in_(["ACTIVE", "SOLD", "ADJUSTED"])).order_by(Lot.id.desc()))
            if lot is None:
                prev = db.scalar(select(Lot).where(Lot.product_id == it["product_id"]).order_by(Lot.id.desc()))
                prod = db.get(Product, it["product_id"])
                lot = Lot(product_id=prod.id, qty_received=0, qty_remaining=0, received_date=t, expiry_date=exp,
                          unit_cost=prev.unit_cost if prev else prod.unit_cost, status="ACTIVE")
                db.add(lot)
                db.flush()
            lot.status = "ACTIVE"
            lot.qty_remaining += diff
            moves = [(lot, diff)]
        else:
            moves, left = [], -diff
            for lot in lots:
                q = min(lot.qty_remaining, left)
                lot.qty_remaining -= q
                left -= q
                if lot.qty_remaining == 0:
                    lot.status = "ADJUSTED"
                moves.append((lot, -q))
        for lot, q in moves:
            v = q * lot.unit_cost
            total += v
            db.add(StockMovement(product_id=it["product_id"], lot_id=lot.id, date=t, type="ADJUST", qty=q,
                                 unit_cost=lot.unit_cost, value=v, ref=ref, reason="DATE_CHECK",
                                 note=f"Kiểm date: HSD {exp:%d/%m/%Y} {'dư' if q > 0 else 'thiếu'} so với sổ"))
    return {"items": len(p.payload["items"]), "net_value": total, "mode": "LOT"}


def _stock_adjust(db: Session, p: Proposal, user: User) -> dict:
    """Thieu: tru tu lo gan het han truoc (khong biet mat o lo nao). Du: cong vao lo moi nhat."""
    if p.payload.get("mode") == "LOT":
        return _lot_adjust(db, p)
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
                                 unit_cost=lot.unit_cost, value=v, ref=ref, reason="COUNT", note="Kiểm kê: dư so với sổ"))
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
                                 unit_cost=lot.unit_cost, value=v, ref=ref, reason="COUNT", note="Kiểm kê: thiếu so với sổ"))
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
