"""Widget trong chat: tool doc phat bang/the so lieu tu chinh du lieu cua tool (khong do LLM viet)."""
import json

from sqlalchemy import select

from app.agent import tools as toolmod
from app.agent import widgets as W
from app.models import User


def _ctx(db):
    return toolmod.ToolContext(db=db, user=db.scalar(select(User).where(User.role == "manager")))


def _widgets(out):
    return [u for u in out.ui if u["type"] == "widget"]


def test_table_caps_rows_and_reports_remainder():
    rows = [{"a": i} for i in range(40)]
    w = W.table("t", [W.col("a", "A", "num")], rows)
    assert len(w["rows"]) == W.MAX_ROWS and w["more"] == 40 - W.MAX_ROWS
    # `total` > so dong truyen vao (da cat o phia tool)
    assert W.table("t", [W.col("a", "A")], rows[:5], total=12)["more"] == 7


def test_table_keeps_only_declared_columns():
    w = W.table("t", [W.col("a", "A")], [{"a": 1, "secret": "x"}])
    assert w["rows"] == [{"a": 1}]


def test_expiring_tool_emits_table_matching_tool_data(db):
    out = toolmod.REGISTRY["get_expiring_lots"].fn(_ctx(db), days=7)
    (w,) = _widgets(out)
    assert w["kind"] == "table" and w["title"]
    shown = {r["name"] for r in w["rows"]}
    assert shown <= {l["name"] for l in out.data["lots"]} | shown  # khong co hang la
    assert len(w["rows"]) + w["more"] == len(out.data["lots"]) + out.data["more"]
    json.dumps(w, default=str)  # phai serialize duoc de luu vao ui_events


def test_inventory_summary_emits_kpis_and_category_table(db):
    out = toolmod.REGISTRY["get_inventory_summary"].fn(_ctx(db))
    kinds = [w["kind"] for w in _widgets(out)]
    assert kinds == ["kpis", "table"]
    kp = _widgets(out)[0]
    total = next(i for i in kp["items"] if i["label"] == "Giá trị tồn kho")
    assert total["value"] == out.data["total_value"]


def test_kpi_tool_emits_comparison(db):
    out = toolmod.REGISTRY["get_kpi_dashboard"].fn(_ctx(db), days=30)
    (w,) = _widgets(out)
    assert w["kind"] == "kpis" and all(i["prev"] is not None for i in w["items"])


def test_search_and_list_proposals_emit_tables(db):
    s = toolmod.REGISTRY["search_products"].fn(_ctx(db), query="Coca")
    assert _widgets(s) and _widgets(s)[0]["kind"] == "table"
    p = toolmod.REGISTRY["list_proposals"].fn(_ctx(db), status="PENDING")
    assert _widgets(p)[0]["kind"] == "table"


def test_widget_never_sent_to_llm():
    # Widget la su kien UI; orchestrator chi gui `result` (out.data) cho LLM, khong gui out.ui
    import inspect

    from app.agent import orchestrator
    src = inspect.getsource(orchestrator.run_turn)
    assert "content = _dump(result)" in src and "_dump(ui" not in src
