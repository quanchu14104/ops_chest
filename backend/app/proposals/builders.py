"""Tao de xuat (Proposal PENDING). KHONG co tac dung phu nao ngoai ghi ban ghi de xuat."""
from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload

from app import audit
from app.fmt import dmy, vnd
from app.clock import now, today
from app.models import Lot, Product, Proposal, Supplier
from app.services import inventory, replenish, reports


def _now() -> datetime:
    return now().replace(tzinfo=None)


def _end_of(d) -> datetime:
    return datetime.combine(d, time(23, 59, 59))


def _still_open():
    """De xuat con duyet (hoac thu lai) duoc: PENDING/FAILED chua qua han chot."""
    return and_(Proposal.status.in_(["PENDING", "FAILED"]),
                or_(Proposal.expires_at.is_(None), Proposal.expires_at >= _now()))


def _existing(db: Session, key: str) -> Proposal | None:
    return db.scalar(select(Proposal).where(Proposal.dedupe_key == key,
                                            or_(Proposal.status.in_(["APPROVED", "EXECUTED"]), _still_open())))


def _open_by_lot(db: Session, type: str) -> dict[int, Proposal]:
    """Lo dang nam trong de xuat con mo. Khoa dedupe co ngay nen khong chan duoc de xuat lap lai qua cac ngay."""
    out: dict[int, Proposal] = {}
    for p in db.scalars(select(Proposal).where(Proposal.type == type, _still_open())):
        for it in p.payload["items"]:
            if int(it["qty"]) > 0:
                out[it["lot_id"]] = p
    return out


def _create(db: Session, *, type: str, title: str, rationale: str, payload: dict, evidence: dict,
            est_value: int | None, created_by: str, dedupe_key: str | None = None,
            expires_at: datetime | None = None, chat_session_id: int | None = None) -> tuple[Proposal, bool]:
    if dedupe_key:
        ex = _existing(db, dedupe_key)
        if ex:
            return ex, False
    p = Proposal(type=type, status="PENDING", title=title, rationale=rationale, evidence=evidence,
                 payload=payload, original_payload=copy.deepcopy(payload), est_value=est_value,
                 created_by=created_by, chat_session_id=chat_session_id, created_at=_now(),
                 expires_at=expires_at, dedupe_key=dedupe_key)
    db.add(p)
    db.flush()
    audit.log(db, created_by, "PROPOSAL_CREATED", "proposal", p.id, {"type": type, "title": title})
    return p, True


def purchase_order(db: Session, supplier: Supplier, created_by: str, chat_session_id: int | None = None
                   ) -> tuple[Proposal | None, bool, dict]:
    sug = replenish.suggest_po(db, supplier)
    if not sug["lines"]:
        return None, False, sug
    t = today()
    top = sorted(sug["lines"], key=lambda l: -l["line_value"])[:5]
    capped = [l["sku"] for l in sug["lines"] if l["explain"]["capped_by_shelf_life"]]
    rationale = (
        f"Đơn cho {supplier.name}: {len(sug['lines'])} mặt hàng, tổng {vnd(sug['total_value'])}, giao ngày "
        f"{dmy(sug['expected_date'])}. Số lượng = dự báo nhu cầu trong {sug['review_period_days']} ngày phủ "
        f"+ tồn an toàn − tồn còn hạn khi hàng về − hàng đang về."
    )
    if capped:
        rationale += f" {len(capped)} mặt hàng bị chặn theo hạn sử dụng (không đặt quá lượng bán kịp trước HSD)."
    payload = {k: sug[k] for k in ("supplier_id", "supplier_code", "supplier_name", "supplier_email", "order_date",
                                   "expected_date", "lines", "total_value", "min_order_value")}
    payload["note"] = ""
    return (*_create(
        db, type="PURCHASE_ORDER", title=f"Đặt hàng {supplier.name} ({len(sug['lines'])} mặt hàng)",
        rationale=rationale, payload=payload,
        evidence={"warnings": sug["warnings"], "top_lines": [
            {"sku": l["sku"], "name": l["name"], "qty": l["qty"], "on_hand": l["on_hand"],
             "forecast_cover": l["forecast_cover"], "mode": l["explain"]["mode"],
             "service_level": l["explain"]["service_level"]} for l in top],
            "capped_by_shelf_life": capped, "lead_time_days": sug["lead_time_days"],
            "review_period_days": sug["review_period_days"]},
        est_value=sug["total_value"], created_by=created_by, chat_session_id=chat_session_id,
        dedupe_key=f"PO:{supplier.code}:{t.isoformat()}", expires_at=_end_of(t),
    ), sug)


def _lot_items(db: Session, lot_ids: list[int] | None, days: int, action: str) -> list[dict]:
    """Lay cac lo co phuong an tot nhat = action (MARKDOWN/RETURN) tu bao cao can date."""
    rep = inventory.expiring_lots(db, days=days)
    out = []
    for it in rep["lots"]:
        if lot_ids is not None and it["lot_id"] not in lot_ids:
            continue
        if it["status"] != "AT_RISK" or not it["options"]:
            continue
        opt = next((o for o in it["options"] if o["action"] == action and o["feasible"]), None)
        if opt is None:
            continue
        if lot_ids is None and it["options"][0]["action"] != action:
            continue  # tu dong: chi lay khi day la phuong an tot nhat
        out.append({**it, "option": opt})
    return out


def markdown(db: Session, created_by: str, lot_ids: list[int] | None = None, days: int = 3,
             evening_only: bool = False, chat_session_id: int | None = None) -> tuple[Proposal | None, bool]:
    items = _lot_items(db, lot_ids, days, "MARKDOWN")
    if evening_only:
        items = [i for i in items if i["days_left"] <= 0]
    if not items:
        return None, False
    t = today()
    payload_items = [{
        "lot_id": i["lot_id"], "sku": i["sku"], "name": i["name"], "qty": i["qty"],
        "expiry_date": i["expiry_date"], "days_left": i["days_left"], "unit_price": i["unit_price"],
        "markdown_pct": i["option"]["markdown_pct"], "timing": i["option"]["timing"],
        "expected_waste_if_keep": i["expected_waste"], "est_gain": i["option"]["delta_vs_keep"],
    } for i in items]
    gain = sum(i["est_gain"] for i in payload_items)
    evening = all(i["timing"] == "EVENING" for i in payload_items)
    title = f"{'Giảm giá giờ vàng' if evening else 'Giảm giá hàng cận date'}: {len(items)} lô"
    rationale = (
        f"{len(items)} lô dự kiến không bán hết trước HSD (theo dự báo nhu cầu, bán FEFO). Giảm giá dự kiến "
        f"thu về thêm khoảng {vnd(gain)} so với để hủy. Mức giảm chọn theo giá trị thu hồi kỳ vọng."
    )
    key = f"MD:{t.isoformat()}:{','.join(str(i['lot_id']) for i in payload_items)}"
    return _create(db, type="MARKDOWN", title=title, rationale=rationale, payload={"items": payload_items},
                   evidence={"options_by_lot": {i["lot_id"]: i["options"] for i in items}}, est_value=int(gain),
                   created_by=created_by, dedupe_key=key, expires_at=_end_of(t), chat_session_id=chat_session_id)


def supplier_return(db: Session, created_by: str, lot_ids: list[int] | None = None, days: int = 60,
                    chat_session_id: int | None = None) -> list[tuple[Proposal, bool]]:
    items = _lot_items(db, lot_ids, days, "RETURN")
    open_by_lot = _open_by_lot(db, "RETURN")
    already = {open_by_lot[i["lot_id"]].id: open_by_lot[i["lot_id"]] for i in items if i["lot_id"] in open_by_lot}
    by_sup: dict[str, list] = {}
    for i in items:
        if i["lot_id"] not in open_by_lot:
            by_sup.setdefault(i["supplier"], []).append(i)
    out: list[tuple[Proposal, bool]] = [(p, False) for p in already.values()]
    t = today()
    for sup_name, its in by_sup.items():
        sup = db.scalar(select(Supplier).options(joinedload(Supplier.agreements)).where(Supplier.name == sup_name))
        agr = sup.agreement_on(t)  # _lot_items chi giu lo co phuong an tra kha thi, tuc thoa thuan con hieu luc
        payload_items = [{"lot_id": i["lot_id"], "sku": i["sku"], "name": i["name"],
                          "qty": int(round(i["option"]["units_returned"])), "lot_qty": i["qty"],
                          "expiry_date": i["expiry_date"], "unit_cost": i["unit_cost"]} for i in its]
        credit = int(sum(x["qty"] * x["unit_cost"] * agr.return_credit_pct for x in payload_items))
        last_day = (min(date.fromisoformat(i["expiry_date"]) for i in its)
                    - timedelta(days=agr.return_min_days_before_expiry))
        key = f"RT:{sup.code}:{t.isoformat()}:{','.join(str(i['lot_id']) for i in payload_items)}"
        out.append(_create(
            db, type="RETURN", title=f"Trả hàng cận date cho {sup.name} ({len(its)} lô)",
            rationale=(f"Thỏa thuận với {sup.name} cho phép trả hàng còn ≥ {agr.return_min_days_before_expiry} ngày "
                       f"trước HSD, hoàn {agr.return_credit_pct:.0%} giá vốn. Trả phần dự kiến không bán kịp, "
                       f"thu về khoảng {vnd(credit)} thay vì hủy."),
            payload={"supplier_id": sup.id, "supplier_name": sup.name, "supplier_email": sup.email,
                     "credit_pct": agr.return_credit_pct, "items": payload_items, "est_credit": credit},
            evidence={"agreement": {"return_min_days_before_expiry": agr.return_min_days_before_expiry,
                                    "return_credit_pct": agr.return_credit_pct}},
            est_value=credit, created_by=created_by, dedupe_key=key, expires_at=_end_of(max(t, last_day)),
            chat_session_id=chat_session_id,
        ))
    return out


def dispose_expired(db: Session, created_by: str, chat_session_id: int | None = None) -> tuple[Proposal | None, bool]:
    t = today()
    lots = db.scalars(select(Lot).options(joinedload(Lot.product))
                      .where(Lot.status == "ACTIVE", Lot.qty_remaining > 0, Lot.expiry_date < t)).all()
    if not lots:
        return None, False
    open_by_lot = _open_by_lot(db, "DISPOSE")
    fresh = [l for l in lots if l.id not in open_by_lot]
    if not fresh:
        return open_by_lot[lots[0].id], False
    lots = fresh
    items = [{"lot_id": l.id, "sku": l.product.sku, "name": l.product.name, "qty": l.qty_remaining,
              "expiry_date": l.expiry_date.isoformat(), "unit_cost": l.unit_cost} for l in lots]
    value = sum(i["qty"] * i["unit_cost"] for i in items)
    key = f"DS:{t.isoformat()}:{','.join(str(i['lot_id']) for i in items)}"
    return _create(
        db, type="DISPOSE", title=f"Ghi nhận hủy {len(items)} lô đã quá hạn",
        rationale=(f"{len(items)} lô đã quá HSD vẫn còn trong kho (giá vốn {vnd(value)}). Cần gỡ khỏi kệ và ghi "
                   "nhận hủy để tồn kho đúng thực tế. Agent không tự ghi hủy."),
        payload={"items": items, "total_cost": value}, evidence={}, est_value=-value, created_by=created_by,
        dedupe_key=key, chat_session_id=chat_session_id)


def delist(db: Session, sku: str, created_by: str, chat_session_id: int | None = None) -> tuple[Proposal | None, bool, str]:
    p = db.scalar(select(Product).where(Product.sku == sku.upper()))
    if not p:
        return None, False, f"Không tìm thấy SKU {sku}"
    if p.status != "ACTIVE":
        return None, False, f"{sku} đã ngừng nhập"
    cands = {c["sku"]: c for c in reports.delist_report(db, limit=500)}
    c = cands.get(p.sku)
    if c is None:
        return None, False, (f"{p.sku} không nằm trong danh sách ứng viên ngừng nhập theo tiêu chí ABC-XYZ "
                             "(nhóm C-Y/C-Z, hủy nhiều hoặc lỗ, không phải hàng kéo khách).")
    prop, created = _create(
        db, type="DELIST", title=f"Ngừng nhập {p.name} ({p.sku})",
        rationale=" ".join(c["reasons"]) + " Hàng còn tồn vẫn bán tiếp đến hết, chỉ dừng đặt mới.",
        payload={"product_id": p.id, "sku": p.sku, "name": p.name}, evidence=c,
        est_value=int(c["margin_90d"]), created_by=created_by, dedupe_key=f"DL:{p.sku}",
        chat_session_id=chat_session_id)
    return prop, created, ""


def demand_hypothesis(db: Session, created_by: str, factor: float, start: date, end: date, reason: str,
                      category: str | None = None, sku: str | None = None,
                      chat_session_id: int | None = None) -> tuple[Proposal, bool]:
    """De xuat ghi nhan gia thuyet cua SM. Chua co tac dung voi du bao cho den khi duoc duyet."""
    from app.services import hypotheses as H

    products, cat, code = H.matching_products(db, category, sku)
    H.validate(db, float(factor), start, end, reason, cat, code)
    pv = H.preview(db, products, float(factor), start, end)
    scope = cat or f"{products[0].name} ({code})"
    rationale = (
        f"Giả thuyết của Store Manager: {reason.strip()}. Nhu cầu {scope} nhân ×{factor:g} từ {dmy(start)} đến {dmy(end)}. "
        f"Dự báo của {pv['sku_count']} mặt hàng trong khoảng này đổi từ {pv['baseline_total']:g} thành "
        f"{pv['adjusted_total']:g} đơn vị. Sau khi kết thúc, hệ thống đối chiếu với lượng bán thực tế để chấm đúng/sai."
    )
    return _create(
        db, type="DEMAND_HYPOTHESIS", title=f"Giả thuyết nhu cầu: {scope} ×{factor:g}", rationale=rationale,
        payload={"category": cat, "sku": code, "scope": scope, "factor": float(factor), "start_date": start.isoformat(),
                 "end_date": end.isoformat(), "reason": reason.strip(), **pv},
        evidence={}, est_value=None, created_by=created_by, chat_session_id=chat_session_id,
        dedupe_key=f"HY:{cat or code}:{start.isoformat()}:{end.isoformat()}:{factor:g}", expires_at=_end_of(today()))


def order_adjustment(db: Session, category: str, created_by: str, chat_session_id: int | None = None
                     ) -> tuple[Proposal | None, bool, str]:
    """Chi tao khi lich su sua cua SM du manh (engine edit_learning): khong cho LLM tu dat he so."""
    from app.services.learning import patterns

    found_all = patterns(db)
    wanted = category.strip().lower()
    matches = ([p for p in found_all if p["category"].lower() == wanted]
               or [p for p in found_all if wanted in p["category"].lower()])
    if len(matches) > 1:
        return None, False, f"'{category}' khớp nhiều nhóm: {', '.join(p['category'] for p in matches)}. Hãy nêu rõ một nhóm."
    found = matches[0] if matches else None
    if not found:
        return None, False, (f"Chưa đủ dấu hiệu để điều chỉnh nhóm '{category}': cần ít nhất 5 lần sửa trên 3 đơn, "
                             "cùng chiều, và lệch từ 15% trở lên.")
    key = f"OA:{found['category']}:{found['factor']:g}"
    recent = db.scalar(select(Proposal).where(Proposal.dedupe_key == key, Proposal.status == "REJECTED",
                                              Proposal.created_at >= _now() - timedelta(days=30)))
    if recent:
        return None, False, f"Đề xuất tương tự #{recent.id} đã bị từ chối trong 30 ngày qua."
    pct_change = abs(found["factor"] - 1)
    verb = "giảm" if found["factor"] < 1 else "tăng"
    rationale = (
        f"Trong {found['proposals']} đơn gần đây, anh/chị đã sửa {found['edits']} dòng nhóm {found['category']}, "
        f"thường {verb} khoảng {pct_change:.0%} so với đề xuất. Nếu duyệt, số lượng đề xuất của nhóm này sẽ nhân "
        f"×{found['factor']:g}. Có thể tắt bất cứ lúc nào."
    )
    prop, created = _create(
        db, type="ORDER_ADJUST", title=f"Điều chỉnh số lượng đặt nhóm {found['category']} ×{found['factor']:g}",
        rationale=rationale, payload={**found, "reason": rationale}, evidence=found, est_value=None,
        created_by=created_by, dedupe_key=key, chat_session_id=chat_session_id)
    return prop, created, ""


def stock_adjust(db: Session, counted: dict[str, int], created_by: str, note: str | None = None,
                 chat_session_id: int | None = None) -> tuple[Proposal | None, int]:
    """Tra ve (de xuat, so dong da dem). Khong lech thi khong tao de xuat."""
    from app.services import stockcount as SC

    items = SC.diffs(db, counted)
    if not items:
        return None, len(counted)
    net = sum(i["value"] for i in items)
    short = sum(1 for i in items if i["diff"] < 0)
    large = [i for i in items if SC.is_large_gap(i["system_qty"], i["diff"])]
    warnings = ([f"Lệch lớn ở {', '.join(i['name'] for i in large[:5])}: nên đếm lại trước khi duyệt."] if large else [])
    prop, _ = _create(
        db, type="STOCK_ADJUST", title=f"Điều chỉnh tồn theo kiểm kê: {len(items)} mặt hàng",
        rationale=(f"Đếm {len(counted)} mặt hàng, {len(items)} mặt hàng lệch so với sổ ({short} thiếu, {len(items) - short} dư). "
                   f"Giá trị lệch ròng {vnd(net)}. Duyệt thì tồn kho được sửa theo số đếm và ghi nhận hao hụt."),
        payload={"items": items, "counted_lines": len(counted), "note": note or ""}, evidence={"warnings": warnings},
        est_value=net, created_by=created_by, expires_at=_end_of(today()), chat_session_id=chat_session_id)
    return prop, len(counted)


class ReviseError(Exception):
    """Yeu cau sua khong hop le (de xuat khong PENDING, SKU khong co trong don, muc giam sai...)."""


def revise(db: Session, proposal_id: int, created_by: str, sku_qty: dict[str, int] | None = None,
           markdown_pct: float | None = None, chat_session_id: int | None = None) -> Proposal:
    """Tao de xuat MOI (PENDING) thay cho de xuat PENDING cu, ban cu chuyen SUPERSEDED (khong duyet duoc nua).

    Chi doc/ghi ban ghi de xuat: khong duyet, khong thuc thi. Ban moi van phai qua Store Manager duyet.
    """
    old = db.get(Proposal, proposal_id)
    if not old:
        raise ReviseError(f"Không tìm thấy đề xuất #{proposal_id}")
    if old.status != "PENDING":
        raise ReviseError(f"Đề xuất #{old.id} đang ở trạng thái {old.status}, chỉ sửa được đề xuất đang chờ duyệt.")
    if old.expires_at and _now() > old.expires_at:
        raise ReviseError(f"Đề xuất #{old.id} đã quá hạn chốt, hãy tạo đề xuất mới.")
    payload = copy.deepcopy(old.payload)
    changes: list[str] = []
    structured: list[dict] = []  # cung dang voi sm_edits khi SM sua tay, de hoc thoi quen sua
    est_value = old.est_value
    if old.type == "PURCHASE_ORDER":
        if not sku_qty:
            raise ReviseError("Cần nêu số lượng mới theo SKU cho đơn đặt hàng.")
        by_sku = {l["sku"].upper(): l for l in payload["lines"]}
        for sku, qty in sku_qty.items():
            line = by_sku.get(sku.upper())
            if line is None:
                raise ReviseError(f"{sku} không có trong đơn #{old.id}")
            qty = int(qty)
            if qty < 0:
                raise ReviseError("Số lượng không được âm")
            if qty != line["qty"]:
                changes.append(f"{line['sku']}: {line['qty']} → {qty}")
                structured.append({"field": f"lines[{line['sku']}].qty", "from": line["qty"], "to": qty})
                line["qty"] = qty
                line["line_value"] = qty * line["unit_cost"]
        payload["total_value"] = sum(int(l["qty"]) * int(l["unit_cost"]) for l in payload["lines"])
        est_value = payload["total_value"]
    elif old.type == "MARKDOWN":
        if markdown_pct is None:
            raise ReviseError("Cần nêu mức giảm giá mới (vd 0.3 = 30%).")
        if not 0 < float(markdown_pct) < 0.95:
            raise ReviseError("Mức giảm giá phải trong khoảng 0–95%")
        for it in payload["items"]:
            if it.get("markdown_pct") != float(markdown_pct):
                changes.append(f"{it['sku']}#{it['lot_id']}: {it['markdown_pct']:.0%} → {float(markdown_pct):.0%}")
                it["markdown_pct"] = float(markdown_pct)
    else:
        raise ReviseError("Loại đề xuất này không sửa được, chỉ đặt hàng và giảm giá.")
    if not changes:
        raise ReviseError("Thay đổi yêu cầu trùng với đề xuất hiện tại, không có gì để sửa.")
    old.status = "SUPERSEDED"
    old.decision_note = f"Được thay bằng bản sửa theo yêu cầu trong chat ({'; '.join(changes)})"
    audit.log(db, created_by, "PROPOSAL_SUPERSEDED", "proposal", old.id, {"changes": changes})
    rationale = f"{old.rationale} [Bản sửa của #{old.id}: {'; '.join(changes)}.]"
    if old.type == "MARKDOWN":
        rationale += " Mức thu thêm ước tính chưa tính lại theo mức giảm mới."
    new, _ = _create(db, type=old.type, title=old.title, rationale=rationale, payload=payload,
                     evidence={**old.evidence, "revised_from": old.id}, est_value=est_value,
                     created_by=created_by, dedupe_key=old.dedupe_key, expires_at=old.expires_at,
                     chat_session_id=chat_session_id or old.chat_session_id)
    if structured:
        new.sm_edits = (old.sm_edits or []) + [{"by": "chat", "at": _now().isoformat(), "changes": structured}]
    audit.log(db, created_by, "PROPOSAL_REVISED", "proposal", new.id, {"from": old.id, "changes": changes})
    return new
