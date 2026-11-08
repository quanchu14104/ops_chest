"""Truy van nhanh KHONG qua LLM: chay thang tool doc cua agent va tra ve widget.

Dung lam duong du phong khi LLM loi/het han muc/chua cau hinh: cac muc ban tin va goi y nhanh van ra
bang/the so lieu that. Chi goi tool kind "read" (kiem tra o day), nen khong the tao de xuat hay ghi gi.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent import tools as toolmod
from app.models import User
from app.services import replenish

# key -> (tieu de, ten tool doc, tham so)
QUICK: dict[str, tuple[str, str, dict]] = {
    "inventory": ("Tồn kho hiện tại", "get_inventory_summary", {}),
    "expiring": ("Lô cận date trong 3 ngày tới", "get_expiring_lots", {"days": 3}),
    "expiring7": ("Lô cận date trong 7 ngày tới", "get_expiring_lots", {"days": 7}),
    "expired": ("Lô đã quá hạn còn trên kệ", "get_expiring_lots", {"days": 0}),
    "kpi": ("KPI 30 ngày", "get_kpi_dashboard", {"days": 30}),
    "pending": ("Đề xuất đang chờ duyệt", "list_proposals", {"status": "PENDING"}),
}
REORDER_PREFIX = "reorder:"


class QuickError(Exception):
    pass


def run(db: Session, user: User, key: str) -> dict:
    if key.startswith(REORDER_PREFIX):
        code = key[len(REORDER_PREFIX):]
        if not replenish.get_supplier(db, code):
            raise QuickError(f"Không tìm thấy nhà cung cấp '{code}'")
        title, tool_name, args = f"Dự kiến đặt hàng {code}", "preview_reorder", {"supplier": code}
    elif key in QUICK:
        title, tool_name, args = QUICK[key]
    else:
        raise QuickError(f"Truy vấn nhanh không hợp lệ: {key}")
    t = toolmod.REGISTRY[tool_name]
    assert t.kind == "read", "truy van nhanh chi duoc chay tool doc"
    out = t.fn(toolmod.ToolContext(db=db, user=user), **args)
    return {"key": key, "title": title, "ui": [u for u in out.ui if u.get("type") == "widget"]}
