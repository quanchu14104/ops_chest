"""Ban tin dau ngay cho man hinh Tro ly: dung tat dinh tu du lieu that, KHONG goi LLM.

Vi vay khong the bia so lieu, chay duoc khi LLM loi/het han muc, va hien ngay khi mo app.
Moi muc co `prompt`: cau hoi gui vao chat khi nguoi dung bam vao muc do.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import today
from app.config import settings
from app.fmt import dmy, vnd
from app.models import Proposal, PurchaseOrder, Supplier
from app.services import datecheck, hypotheses, inventory, receiving, replenish, shelf


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
                      "text": (f"{len(expired)} lô đã quá ngày bán cuối còn trên kệ, giá vốn "
                               f"{vnd(summ['value_already_expired_on_shelf'])}: gỡ khỏi kệ ngay và xác nhận số thực gỡ"),
                      "prompt": "Có lô nào đã quá hạn còn trên kệ không? Nên xử lý thế nào?", "quick": "pull"})
    pull_today = [x for x in shelf.pull_list(db) if x["overdue_days"] == 0]
    if pull_today:
        items.append({"id": "pull", "level": "info", "count": len(pull_today),
                      "text": f"{len(pull_today)} lô hết ngày bán hôm nay: rút kệ sau giờ đóng cửa ({settings.closing_hour}h)",
                      "prompt": "Tối nay cần rút kệ những lô nào?", "quick": "pull"})
    if summ.get("value_pulled_awaiting_writeoff"):
        n_pulled = len(shelf.pulled_awaiting(db))
        items.append({"id": "pulled", "level": "info", "count": n_pulled,
                      "text": f"{n_pulled} lô đã rút kệ chờ duyệt ghi hủy, giá vốn trên sổ {vnd(summ['value_pulled_awaiting_writeoff'])}",
                      "prompt": "Liệt kê các đề xuất đang chờ duyệt và cho biết cái nào nên xử lý trước"})
    classes = datecheck.due_classes()
    n_check = len([x for c in classes for x in datecheck.sheet(db, c)])
    if n_check:
        labels = ", ".join(datecheck.CLASS_LABEL[c] for c in classes)
        items.append({"id": "date_check", "level": "info", "count": n_check,
                      "text": f"Hôm nay kiểm date {labels}: {n_check} mặt hàng có lô sắp tới ngày bán cuối",
                      "prompt": "Mở phiếu kiểm date hôm nay", "quick": "date_check"})
    for s in receiving.recent_shortages(db, days=3):
        items.append({"id": f"short-{s['code']}", "level": "warn", "count": s["lines"],
                      "text": f"Đơn {s['code']} ({s['supplier']}) giao thiếu {s['lines']} mặt hàng, {s['units']} đơn vị",
                      "prompt": "Nhà cung cấp nào hay giao thiếu?"})
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
    for s in db.scalars(select(Supplier).order_by(Supplier.code)):
        c = replenish.upcoming_closure(s, today(), within_days=14)
        if c:
            items.append({"id": f"closure-{s.code}", "level": "warn", "count": 1,
                          "text": replenish.closure_text(s, c), "prompt": f"Lên đơn đặt hàng cho {s.name}",
                          "quick": f"reorder:{s.code}"})
    if summ["purchase_orders_awaiting_delivery"]:
        items.append({"id": "po", "level": "info", "count": summ["purchase_orders_awaiting_delivery"],
                      "text": f"{summ['purchase_orders_awaiting_delivery']} đơn hàng đang chờ giao",
                      "prompt": "Có đơn đặt hàng nào đang chờ giao không?"})
    late = db.scalar(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.status == "SENT", PurchaseOrder.expected_date < today()))
    if late:
        items.append({"id": "po_late", "level": "warn", "count": late,
                      "text": f"{late} đơn đã quá ngày giao dự kiến: hỏi lại nhà cung cấp, không giao nữa thì huỷ đơn",
                      "prompt": "Có đơn đặt hàng nào đang chờ giao không?"})
    if summ["out_of_stock_skus"]:
        items.append({"id": "oos", "level": "warn", "count": summ["out_of_stock_skus"],
                      "text": f"{summ['out_of_stock_skus']} mặt hàng đang hết hàng",
                      "prompt": "Tình hình kho hôm nay thế nào? Mặt hàng nào đang hết?", "quick": "inventory"})
    for x in hypotheses.recently_evaluated(db):
        v = hypotheses.view(x)
        items.append({"id": f"hypothesis-{x.id}", "level": "info", "count": 1,
                      "text": f"Giả thuyết \"{x.reason}\" ({v['scope']} ×{x.factor:g}): {v['verdict_label']}",
                      "prompt": "Các giả thuyết nhu cầu của tôi gần đây đúng hay sai?"})
    return {"today": today().isoformat(), "date_label": dmy(today()), "items": items,
            "all_clear": not items}
