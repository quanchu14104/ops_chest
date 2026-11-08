"""Ban tin dau ngay cho man hinh Tro ly: dung tat dinh tu du lieu that, KHONG goi LLM.

Vi vay khong the bia so lieu, chay duoc khi LLM loi/het han muc, va hien ngay khi mo app.
Moi muc co `prompt`: cau hoi gui vao chat khi nguoi dung bam vao muc do.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import today
from app.fmt import dmy, vnd
from app.models import Proposal
from app.services import inventory, replenish


def build(db: Session) -> dict:
    summ = inventory.inventory_summary(db)
    exp = inventory.expiring_lots(db, days=3, with_options=False)
    risky = [l for l in exp["lots"] if l["status"] != "OK"]
    expired = [l for l in risky if l["status"] == "EXPIRED"]
    pending = db.scalars(select(Proposal).where(Proposal.status == "PENDING")).all()
    due = replenish.suppliers_due(db)

    items: list[dict] = []
    if pending:
        total = sum(p.est_value or 0 for p in pending if p.type == "PURCHASE_ORDER")
        extra = f" (đơn đặt hàng tổng {vnd(total)})" if total else ""
        items.append({"id": "pending", "level": "action", "count": len(pending),
                      "text": f"{len(pending)} đề xuất đang chờ anh/chị duyệt{extra}",
                      "prompt": "Liệt kê các đề xuất đang chờ duyệt và cho biết cái nào nên xử lý trước", "quick": "pending"})
    if expired:
        items.append({"id": "expired", "level": "action", "count": len(expired),
                      "text": f"{len(expired)} lô đã quá hạn còn trên kệ, giá vốn {vnd(summ['value_already_expired_on_shelf'])}",
                      "prompt": "Có lô nào đã quá hạn còn trên kệ không? Nên xử lý thế nào?", "quick": "expired"})
    near = [l for l in risky if l["status"] != "EXPIRED"]
    if near:
        items.append({"id": "expiring", "level": "warn", "count": len(near),
                      "text": f"{len(near)} lô có nguy cơ hủy trong 3 ngày tới, giá vốn rủi ro {vnd(exp['total_value_at_risk'])}",
                      "prompt": "Hàng nào sắp hết hạn trong 3 ngày tới, nên xử lý thế nào?", "quick": "expiring"})
    if due:
        names = ", ".join(s.name for s in due)
        items.append({"id": "due", "level": "info", "count": len(due),
                      "text": f"Hôm nay đến lịch đặt hàng: {names}",
                      "prompt": f"Lên đơn đặt hàng cho {due[0].name}", "quick": f"reorder:{due[0].code}"})
    if summ["purchase_orders_awaiting_delivery"]:
        items.append({"id": "po", "level": "info", "count": summ["purchase_orders_awaiting_delivery"],
                      "text": f"{summ['purchase_orders_awaiting_delivery']} đơn hàng đang chờ giao",
                      "prompt": "Có đơn đặt hàng nào đang chờ giao không?"})
    if summ["out_of_stock_skus"]:
        items.append({"id": "oos", "level": "warn", "count": summ["out_of_stock_skus"],
                      "text": f"{summ['out_of_stock_skus']} mặt hàng đang hết hàng",
                      "prompt": "Tình hình kho hôm nay thế nào? Mặt hàng nào đang hết?", "quick": "inventory"})
    return {"today": today().isoformat(), "date_label": dmy(today()), "items": items,
            "all_clear": not items}
