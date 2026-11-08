"""Tao de xuat (Proposal PENDING). KHONG co tac dung phu nao ngoai ghi ban ghi de xuat."""
from __future__ import annotations

import copy
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import audit
from app.fmt import dmy, vnd
from app.clock import now, today
from app.models import Lot, Product, Proposal, Supplier
from app.services import inventory, replenish, reports


def _now() -> datetime:
    return now().replace(tzinfo=None)


def _end_of(d) -> datetime:
    return datetime.combine(d, time(23, 59))


def _existing(db: Session, key: str) -> Proposal | None:
    return db.scalar(select(Proposal).where(Proposal.dedupe_key == key,
                                            Proposal.status.in_(["PENDING", "APPROVED", "EXECUTED"])))


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
    by_sup: dict[str, list] = {}
    for i in items:
        by_sup.setdefault(i["supplier"], []).append(i)
    out = []
    t = today()
    for sup_name, its in by_sup.items():
        sup = db.scalar(select(Supplier).options(joinedload(Supplier.agreements)).where(Supplier.name == sup_name))
        agr = sup.agreements[0]
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
