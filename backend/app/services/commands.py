"""Lenh nhanh trong chat: chay thang mot tool cua agent, KHONG qua LLM, va ghi vao hoi thoai.

Muc dich: moi viec cua cua hang mo duoc ngay trong chat trong chua toi mot giay (LLM mat 45-112s moi luot
co tool), con cau go tu do van di qua LLM. Ghi vao hoi thoai giong het mot luot agent goi tool
(user -> assistant(tool_calls) -> tool), nen tai lai lich su van thay the, va LLM o luot sau biet da hien gi.

QUY TAC HITL (test kiem tra): chi chay tool kind "read" hoac "propose" (tao de xuat PENDING). Module nay
KHONG import proposals.executor hay proposals.service. Quet buoi sang chi tao de xuat PENDING.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.agent import tools as toolmod
from app.agent.orchestrator import _dump
from app.clock import now
from app.models import ChatMessage, ChatSession, User

# ten lenh -> (nhan hien trong chat, tool, tham so mac dinh)
COMMANDS: dict[str, tuple[str, str, dict]] = {
    "pending": ("Đề xuất chờ duyệt", "open_approval_inbox", {}),
    "lots": ("Hàng cận date", "open_expiring_panel", {"days": 3}),
    "pull": ("Rút kệ cuối ngày", "open_pull_form", {}),
    "date_check": ("Kiểm date hôm nay", "open_date_check_form", {}),
    "count_due": ("Kiểm kê đến lịch", "open_stock_count_form", {"due": True}),
    "orders": ("Đơn chờ giao", "open_purchase_orders", {}),
    "receive": ("Nhận hàng", "open_receive_form", {}),
    "returns": ("Phiếu trả NCC", "open_supplier_returns", {}),
    "inventory": ("Tồn kho", "get_inventory_summary", {}),
    "oos": ("Mặt hàng đang hết", "search_products", {"out_of_stock": True, "limit": 20}),
    "kpi": ("KPI 30 ngày", "get_kpi_dashboard", {"days": 30}),
    "hypotheses": ("Giả thuyết nhu cầu", "list_demand_hypotheses", {}),
    "order": ("Đặt hàng", "propose_purchase_order", {}),
    "scan": ("Quét & tạo đề xuất", "open_approval_inbox", {}),
}
# Lenh co doi so sau dau ":" -> ten tham so cua tool
ARG: dict[str, str] = {"pending": "type", "lots": "days", "receive": "po", "order": "supplier"}
LABEL_ARG: dict[str, str] = {"receive": "đơn", "order": "NCC"}


class CommandError(Exception):
    pass


def resolve(key: str) -> tuple[str, str, dict]:
    name, _, arg = key.partition(":")
    if name not in COMMANDS:
        raise CommandError(f"Lệnh không hợp lệ: {key}")
    label, tool_name, args = COMMANDS[name]
    args = dict(args)
    if arg:
        if name not in ARG:
            raise CommandError(f"Lệnh {name} không nhận tham số")
        args[ARG[name]] = int(arg) if name == "lots" and arg.isdigit() else arg
        if name in LABEL_ARG:
            label = f"{label} · {LABEL_ARG[name]} {arg}"
        elif name == "lots":
            label = f"{label} · {arg} ngày"
    elif name in ("receive", "order"):
        raise CommandError(f"Lệnh {name} cần tham số, ví dụ {name}:...")
    return label, tool_name, args


def _ts() -> datetime:
    return now().replace(tzinfo=None)


def run(db: Session, session: ChatSession, user: User, key: str) -> dict:
    label, tool_name, args = resolve(key)
    t = toolmod.REGISTRY[tool_name]
    assert t.kind in ("read", "propose"), "lenh nhanh chi duoc chay tool doc hoac tao de xuat"
    if key.partition(":")[0] == "scan":
        # Giong nut "Quet & tao de xuat ngay" (job 06:30): chi tao de xuat PENDING
        from app.jobs.daily import run_morning
        run_morning(db)

    ctx = toolmod.ToolContext(db=db, user=user, chat_session_id=session.id)
    try:
        out = t.fn(ctx, **args)
        data, ui = out.data, out.ui
    except Exception as e:  # noqa: BLE001 - loi tool hien trong chat nhu luot agent, khong lam hong hoi thoai
        db.rollback()
        data, ui = {"error": f"{type(e).__name__}: {e}"}, []
    if isinstance(data, dict) and data.get("error") and not ui:
        ui = [{"type": "widget", "kind": "table", "title": label, "columns": [], "rows": [], "more": 0,
               "note": None, "empty": str(data["error"])}]

    # Ghi nhu mot luot agent goi tool: user -> assistant(tool_calls, name="command") -> tool
    tc_id = f"cmd_{uuid.uuid4().hex[:12]}"
    tool_calls = [{"id": tc_id, "type": "function",
                   "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}}]
    db.add(ChatMessage(session_id=session.id, role="user", content=f"▸ {label}", created_at=_ts()))
    db.add(ChatMessage(session_id=session.id, role="assistant", content="", name="command",
                       tool_calls=tool_calls, created_at=_ts()))
    db.add(ChatMessage(session_id=session.id, role="tool", tool_call_id=tc_id, name=tool_name,
                       content=_dump(data), ui_events=ui or None, created_at=_ts()))
    if session.title == "Hội thoại mới":
        session.title = label[:60]
    db.commit()
    return {"key": key, "label": label, "tool": tool_name, "ui": ui,
            "error": data.get("error") if isinstance(data, dict) else None}
