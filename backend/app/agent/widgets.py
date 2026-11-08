"""Widget hien thi trong chat (bang, the so lieu) do TOOL phat ra, khong phai do LLM viet.

So lieu trong widget lay thang tu ket qua tool nen luon khop du lieu that; LLM chi can tom tat 2-3 y.
Widget la su kien UI thuan (khong gui lai cho LLM), luu cung tin nhan `tool` nen tai lai lich su van thay.

Dinh dang cot (`fmt`): text | num | money | pct | date | days | badge. Frontend: components/Widgets.tsx.
"""
from __future__ import annotations

from typing import Any

MAX_ROWS = 25


def col(key: str, label: str, fmt: str = "text") -> dict:
    return {"key": key, "label": label, "fmt": fmt}


def table(title: str, columns: list[dict], rows: list[dict], *, note: str | None = None,
          total: int | None = None, empty: str = "Không có dữ liệu.") -> dict:
    """`total` = tong so dong that su neu `rows` da bi cat; UI hien "va N dong nua"."""
    keys = [c["key"] for c in columns]
    shown = [{k: r.get(k) for k in keys} for r in rows[:MAX_ROWS]]
    more = max(0, (total if total is not None else len(rows)) - len(shown))
    return {"type": "widget", "kind": "table", "title": title, "columns": columns, "rows": shown,
            "more": more, "note": note, "empty": empty}


def kpis(title: str, items: list[dict], *, note: str | None = None) -> dict:
    """items: {label, value, fmt, prev?, lower_is_better?}. `prev` (neu co) de UI ve muc tang/giam."""
    return {"type": "widget", "kind": "kpis", "title": title, "items": items, "note": note}


def form(form_id: str, title: str, lines: list[dict], submit: dict, *, note: str | None = None,
         meta: dict | None = None) -> dict:
    """Form nhap lieu trong chat. Tool CHI phat form; ghi du lieu that do nguoi dung bam nut, UI goi
    `submit` (endpoint REST co kiem quyen). `lines`: {line_id, sku, name, qty, received_qty?, default_expiry}."""
    return {"type": "widget", "kind": "form", "form": form_id, "title": title, "meta": meta or {},
            "lines": lines, "submit": submit, "note": note}


def kpi(label: str, value: Any, fmt: str = "num", prev: Any = None, lower_is_better: bool = False) -> dict:
    return {"label": label, "value": value, "fmt": fmt, "prev": prev, "lower_is_better": lower_is_better}
