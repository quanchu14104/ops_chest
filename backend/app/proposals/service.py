"""Vong doi de xuat: PENDING -> (sua) -> APPROVED -> EXECUTED | FAILED; hoac REJECTED / EXPIRED / SUPERSEDED (da duoc agent thay bang ban sua)."""
from __future__ import annotations

import copy
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.clock import now, today
from app.models import Product, Proposal, User
from app.proposals import executor
from app.proposals.views import acceptance_stats, to_dict  # noqa: F401 (re-export)

log = logging.getLogger(__name__)


class ProposalError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _now():
    return now().replace(tzinfo=None)


def _lock(db: Session, pid: int) -> Proposal:
    p = db.execute(select(Proposal).where(Proposal.id == pid).with_for_update()).scalar_one_or_none()
    if not p:
        raise ProposalError(404, "Không tìm thấy đề xuất")
    return p


def _check_open(db: Session, p: Proposal, allow_failed: bool = False) -> None:
    allowed = ("PENDING", "FAILED") if allow_failed else ("PENDING",)
    if p.status not in allowed:
        if p.status == "SUPERSEDED":
            raise ProposalError(409, "Đề xuất này đã được thay bằng bản sửa mới, hãy duyệt bản mới.")
        raise ProposalError(409, f"Đề xuất đang ở trạng thái {p.status}, không thể thao tác.")
    if p.expires_at and _now() > p.expires_at:  # ca FAILED: so lieu cua mot don cu khong con dung de thu lai
        p.status = "EXPIRED"
        audit.log(db, "system", "PROPOSAL_EXPIRED", "proposal", p.id)
        db.commit()
        raise ProposalError(409, "Đề xuất đã hết hiệu lực (quá hạn chốt). Hãy tạo đề xuất mới.")


def apply_edits(db: Session, p: Proposal, edits: dict, user: User) -> list[dict]:
    """Chi cho sua cac truong an toan. Ghi lai diff de do do tin cay cua agent."""
    payload = copy.deepcopy(p.payload)
    diffs: list[dict] = []
    if p.type == "PURCHASE_ORDER":
        by_pid = {l["product_id"]: l for l in payload["lines"]}
        for e in edits.get("lines", []):
            pid = int(e["product_id"])
            qty = int(e["qty"])
            if qty < 0:
                raise ProposalError(422, "Số lượng không được âm")
            if pid in by_pid:
                old = by_pid[pid]["qty"]
                if old != qty:
                    by_pid[pid]["qty"] = qty
                    by_pid[pid]["line_value"] = qty * by_pid[pid]["unit_cost"]
                    diffs.append({"field": f"lines[{by_pid[pid]['sku']}].qty", "from": old, "to": qty})
            else:
                prod = db.get(Product, pid)
                if not prod or prod.supplier_id != payload["supplier_id"]:
                    raise ProposalError(422, f"Sản phẩm {pid} không thuộc nhà cung cấp của đơn này")
                # Dong SM tu them cung huong chiet khau cua thoa thuan nhu dong do engine tao
                agr = prod.supplier.agreement_on(today())
                unit_cost = int(round(prod.unit_cost * (1 - (agr.discount_pct if agr else 0.0))))
                line = {"product_id": pid, "sku": prod.sku, "name": prod.name, "qty": qty, "suggested_qty": 0,
                        "pack_size": prod.pack_size, "unit_cost": unit_cost, "line_value": qty * unit_cost,
                        "added_by_sm": True}
                payload["lines"].append(line)
                diffs.append({"field": f"lines[{prod.sku}]", "from": None, "to": qty})
        payload["total_value"] = sum(int(l["qty"]) * int(l["unit_cost"]) for l in payload["lines"])
        if "note" in edits and edits["note"] != payload.get("note"):
            diffs.append({"field": "note", "from": payload.get("note"), "to": edits["note"]})
            payload["note"] = edits["note"]
        if "min_order_ack" in edits and bool(edits["min_order_ack"]) != bool(payload.get("min_order_ack")):
            diffs.append({"field": "min_order_ack", "from": bool(payload.get("min_order_ack")),
                          "to": bool(edits["min_order_ack"])})
            payload["min_order_ack"] = bool(edits["min_order_ack"])
    elif p.type in ("MARKDOWN", "RETURN", "DISPOSE"):
        by_lot = {i["lot_id"]: i for i in payload["items"]}
        for e in edits.get("items", []):
            it = by_lot.get(int(e["lot_id"]))
            if not it:
                raise ProposalError(422, f"Lô {e['lot_id']} không có trong đề xuất")
            for field in ("qty", "markdown_pct", "include"):
                if field in e and e[field] != it.get(field):
                    if field == "qty" and int(e[field]) < 0:
                        raise ProposalError(422, "Số lượng không được âm")
                    if field == "markdown_pct" and not 0 < float(e[field]) < 0.95:
                        raise ProposalError(422, "Mức giảm giá phải trong khoảng 0–95%")
                    diffs.append({"field": f"items[{it['sku']}#{it['lot_id']}].{field}", "from": it.get(field),
                                  "to": e[field]})
                    it[field] = e[field]
        if p.type == "RETURN":
            payload["est_credit"] = int(sum(int(i["qty"]) * i["unit_cost"] * payload["credit_pct"] for i in payload["items"]))
    elif edits:
        raise ProposalError(422, "Loại đề xuất này không sửa được, chỉ duyệt hoặc từ chối.")
    if diffs:
        p.payload = payload
        p.sm_edits = (p.sm_edits or []) + [{"by": user.username, "at": _now().isoformat(), "changes": diffs}]
        audit.log(db, user.username, "PROPOSAL_EDITED", "proposal", p.id, {"changes": diffs})
    return diffs


def edit(db: Session, pid: int, edits: dict, user: User) -> Proposal:
    p = _lock(db, pid)
    _check_open(db, p)
    apply_edits(db, p, edits, user)
    db.commit()
    return p


def approve(db: Session, pid: int, user: User, note: str | None = None, edits: dict | None = None) -> Proposal:
    if user.role != "manager":
        raise ProposalError(403, "Chỉ Store Manager được duyệt đề xuất")
    p = _lock(db, pid)
    _check_open(db, p, allow_failed=True)
    if edits:
        apply_edits(db, p, edits, user)
    p.status = "APPROVED"
    p.decided_by = user.username
    p.decided_at = _now()
    p.decision_note = note
    audit.log(db, user.username, "PROPOSAL_APPROVED", "proposal", p.id, {"note": note})
    try:
        result = executor.execute(db, p, user)
    except Exception as e:  # noqa: BLE001 - moi loi deu phai rollback & ghi FAILED
        log.exception("Thuc thi de xuat %s that bai", pid)
        db.rollback()
        p = db.get(Proposal, pid)
        if edits:
            apply_edits(db, p, edits, user)
        p.status = "FAILED"
        p.decided_by = user.username
        p.decided_at = _now()
        p.decision_note = note
        msg = str(e) if isinstance(e, executor.ExecutionError) else f"{type(e).__name__}: {e}"
        p.execution_result = {"error": msg}
        audit.log(db, user.username, "PROPOSAL_FAILED", "proposal", p.id, {"error": msg})
        db.commit()
        return p
    p.status = "EXECUTED"
    p.executed_at = _now()
    p.execution_result = result
    audit.log(db, user.username, "PROPOSAL_EXECUTED", "proposal", p.id, result)
    db.commit()
    return p


def reject(db: Session, pid: int, user: User, reason: str) -> Proposal:
    if user.role != "manager":
        raise ProposalError(403, "Chỉ Store Manager được từ chối đề xuất")
    if not reason or not reason.strip():
        raise ProposalError(422, "Cần ghi lý do từ chối (để agent học và để đối chiếu sau).")
    p = _lock(db, pid)
    _check_open(db, p, allow_failed=True)
    p.status = "REJECTED"
    p.decided_by = user.username
    p.decided_at = _now()
    p.decision_note = reason
    audit.log(db, user.username, "PROPOSAL_REJECTED", "proposal", p.id, {"reason": reason})
    db.commit()
    return p


def expire_stale(db: Session) -> int:
    rows = db.scalars(select(Proposal).where(Proposal.status.in_(["PENDING", "FAILED"]), Proposal.expires_at < _now())).all()
    for p in rows:
        p.status = "EXPIRED"
        audit.log(db, "system", "PROPOSAL_EXPIRED", "proposal", p.id)
    db.commit()
    return len(rows)
