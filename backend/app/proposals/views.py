"""Ham chi doc ve de xuat (dung cho API va agent). Khong chua thao tac thay doi trang thai."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Proposal


def subtype(p: Proposal) -> str | None:
    """Phan loai chi tiet de giao dien/agent hien dung: ghi huy het han vs bao huy co ly do, kiem ke SKU vs kiem date."""
    pl = p.payload or {}
    if p.type == "DISPOSE":
        return "EXPIRED" if all(i.get("reason", "EXPIRED") == "EXPIRED" for i in pl.get("items", [])) else "WRITE_OFF"
    if p.type == "STOCK_ADJUST":
        return pl.get("mode", "SKU")
    return None


def to_dict(p: Proposal) -> dict:
    return {
        "id": p.id, "type": p.type, "subtype": subtype(p), "status": p.status, "title": p.title,
        "rationale": p.rationale,
        "evidence": p.evidence, "payload": p.payload, "original_payload": p.original_payload,
        "sm_edits": p.sm_edits or [], "est_value": p.est_value, "created_by": p.created_by,
        "chat_session_id": p.chat_session_id,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "expires_at": p.expires_at.isoformat() if p.expires_at else None,
        "decided_by": p.decided_by, "decided_at": p.decided_at.isoformat() if p.decided_at else None,
        "decision_note": p.decision_note,
        "executed_at": p.executed_at.isoformat() if p.executed_at else None,
        "execution_result": p.execution_result,
    }


def acceptance_stats(db: Session) -> dict:
    """Do do tin cay cua agent: ty le duyet, ty le bi sua, muc chenh so luong."""
    rows = db.scalars(select(Proposal).where(Proposal.status.in_(["EXECUTED", "FAILED", "REJECTED", "EXPIRED"]))).all()
    decided = [p for p in rows if p.status != "EXPIRED"]
    approved = [p for p in decided if p.status in ("EXECUTED", "FAILED")]
    edited = [p for p in approved if p.sm_edits]
    qty_changes = []
    for p in edited:
        for e in p.sm_edits:
            for c in e["changes"]:
                if c["field"].endswith(".qty") and isinstance(c["from"], (int, float)) and c["from"]:
                    qty_changes.append(abs(c["to"] - c["from"]) / c["from"])
    by_type: dict[str, dict] = {}
    for p in decided:
        t = by_type.setdefault(p.type, {"decided": 0, "approved": 0})
        t["decided"] += 1
        t["approved"] += p.status in ("EXECUTED", "FAILED")
    return {
        "decided": len(decided), "approved": len(approved), "rejected": len(decided) - len(approved),
        "expired": len(rows) - len(decided),
        "approval_rate": round(len(approved) / len(decided), 3) if decided else None,
        "edited_rate": round(len(edited) / len(approved), 3) if approved else None,
        "avg_qty_change_pct": round(sum(qty_changes) / len(qty_changes), 3) if qty_changes else None,
        "by_type": by_type,
    }
