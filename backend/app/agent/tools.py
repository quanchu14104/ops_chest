"""Tool registry cho agent.

QUY TAC HITL (duoc test kiem tra):
- Chi co 2 loai tool: "read" (doc du lieu) va "propose" (tao Proposal PENDING qua proposals.builders).
- Module nay KHONG import proposals.executor hay proposals.service.approve.
- Truy van co tham so co dinh; LLM khong viet SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.agent import widgets as W
from app.models import Proposal, PurchaseOrder, Supplier, User
from app.proposals import builders
from app.proposals.views import acceptance_stats, to_dict
from app.services import charts, hypotheses, inventory, learning, replenish, reports, stockcount
from app.services.receiving import default_expiry  # chi lay HSD goi y; viec nhan hang that di qua REST


@dataclass
class ToolContext:
    db: Session
    user: User
    chat_session_id: int | None = None


@dataclass
class ToolOutput:
    data: Any
    ui: list[dict] = field(default_factory=list)  # su kien hien thi: chart / proposal


@dataclass
class Tool:
    name: str
    kind: str  # read / propose
    description: str
    parameters: dict
    fn: Callable[..., ToolOutput]

    def schema(self) -> dict:
        # Tham so tuy chon cho phep null: nhieu model gui null thay vi bo qua, va mot so provider
        # (vd Groq) kiem tra schema nghiem ngat -> tu choi ca luot goi neu chi khai bao "string".
        params = {**self.parameters, "properties": {}}
        req = set(self.parameters.get("required", []))
        for k, v in self.parameters["properties"].items():
            if k not in req and isinstance(v.get("type"), str):
                v = {**v, "type": [v["type"], "null"]}
            params["properties"][k] = v
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": params}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, kind: str, description: str, properties: dict | None = None, required: list[str] | None = None):
    assert kind in ("read", "propose")

    def deco(fn):
        REGISTRY[name] = Tool(name, kind, description,
                              {"type": "object", "properties": properties or {}, "required": required or []}, fn)
        return fn
    return deco


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


DATE = {"type": "string", "description": "YYYY-MM-DD"}
GROUP = {"type": "string", "enum": ["day", "week", "month"]}
CATEGORY = {"type": "string", "description": "category name (partial), e.g. 'Nước ngọt'"}
SKU = {"type": "string", "description": "e.g. COM002"}


# ---------------- READ ----------------
@tool("get_inventory_summary", "read", "Current stock overview: SKU counts, stock value by category, out-of-stock SKUs, value expiring within 3 days, pending proposals.")
def _inventory_summary(ctx: ToolContext) -> ToolOutput:
    s = inventory.inventory_summary(ctx.db)
    ui = [W.kpis("Tồn kho hiện tại", [
        W.kpi("Giá trị tồn kho", s["total_value"], "money"),
        W.kpi("SKU hết hàng", s["out_of_stock_skus"], "num", lower_is_better=True),
        W.kpi("Sắp hết hạn (≤3 ngày)", s["value_expiring_within_3_days"], "money", lower_is_better=True),
        W.kpi("Đã quá hạn trên kệ", s["value_already_expired_on_shelf"], "money", lower_is_better=True),
        W.kpi("Đề xuất chờ duyệt", s["pending_proposals"], "num"),
        W.kpi("Đơn đang chờ giao", s["purchase_orders_awaiting_delivery"], "num"),
    ]), W.table("Tồn kho theo nhóm hàng", [
        W.col("category", "Nhóm"), W.col("skus", "SKU", "num"), W.col("units", "Số lượng", "num"),
        W.col("value", "Giá trị", "money"), W.col("out_of_stock", "Hết hàng", "num")], s["by_category"])]
    return ToolOutput(s, ui=ui)


@tool("search_products", "read", "Find products by name/SKU/category. Returns SKU, prices, on-hand qty.",
      {"query": {"type": "string"}, "category": CATEGORY})
def _search_products(ctx: ToolContext, query: str | None = None, category: str | None = None) -> ToolOutput:
    prods = inventory.find_products(ctx.db, query, category, limit=25)
    lots = inventory.active_lots(ctx.db, [p.id for p in prods])
    rows = [{"sku": p.sku, "name": p.name, "category": p.category, "status": p.status,
             "unit_price": p.unit_price, "unit_cost": p.unit_cost, "supplier": p.supplier.name,
             "on_hand": sum(l.qty_remaining for l in lots.get(p.id, []))} for p in prods]
    ui = [W.table("Kết quả tìm sản phẩm", [
        W.col("sku", "SKU"), W.col("name", "Tên"), W.col("category", "Nhóm"), W.col("on_hand", "Tồn", "num"),
        W.col("unit_price", "Giá bán", "money"), W.col("supplier", "NCC")], rows, empty="Không tìm thấy sản phẩm.")]
    return ToolOutput(rows, ui=ui)


@tool("get_product_detail", "read", "One SKU: lots with expiry, incoming POs, 28-day sales, 14-day forecast, ABC-XYZ cell.", {"sku": SKU}, ["sku"])
def _product_detail(ctx: ToolContext, sku: str) -> ToolOutput:
    d = inventory.product_detail(ctx.db, sku.upper())
    return ToolOutput(d if d else {"error": f"Không tìm thấy SKU {sku}"})


@tool("get_expiring_lots", "read", "Lots expiring within N days (plus expired lots still on shelf) that are at risk of waste, with expected waste and best handling option.",
      {"days": {"type": "integer", "default": 7}, "category": CATEGORY})
def _expiring(ctx: ToolContext, days: int = 7, category: str | None = None) -> ToolOutput:
    r = inventory.expiring_lots(ctx.db, days=days, category=category)
    # Chi tra lo co nguy co (lo "OK" khong can LLM doc); phuong an tot nhat rut gon
    risky = [it for it in r["lots"] if it["status"] != "OK"]
    lots = [{k: it[k] for k in ("lot_id", "sku", "name", "qty", "expiry_date", "days_left", "status",
                                 "expected_waste", "value_at_risk", "supplier")}
            | ({"best": {"label": it["options"][0]["label"], "gain": it["options"][0]["delta_vs_keep"]}}
               if it["options"] else {}) for it in risky]
    rows = [{**l, "best_label": (l.get("best") or {}).get("label"), "best_gain": (l.get("best") or {}).get("gain")}
            for l in lots]
    ui = [W.table(f"Lô cận date trong {days} ngày tới",
                  [W.col("name", "Hàng"), W.col("days_left", "Còn hạn", "days"), W.col("qty", "SL", "num"),
                   W.col("status", "Trạng thái", "badge"), W.col("value_at_risk", "Giá vốn rủi ro", "money"),
                   W.col("best_label", "Phương án tốt nhất")],
                  sorted(rows, key=lambda x: x["days_left"]), total=len(lots),
                  empty="Không có lô nào có nguy cơ hủy.")]
    return ToolOutput({"as_of": r["as_of"], "summary": r["summary"], "total_value_at_risk": r["total_value_at_risk"],
                       "lots": lots[:20], "more": max(0, len(lots) - 20)}, ui=ui)


@tool("get_stock_flow", "read", "Stock in (received) / out (sold, wasted, returned) over time. Default last 30 days.",
      {"start": DATE, "end": DATE, "group_by": GROUP, "category": CATEGORY, "sku": SKU})
def _stock_flow(ctx: ToolContext, start=None, end=None, group_by="day", category=None, sku=None) -> ToolOutput:
    s, e = reports.default_range(_d(start), _d(end))
    rows = reports.stock_flow(ctx.db, s, e, group_by, category, sku)
    totals = {k: sum(r[k] for r in rows) for k in ("in_qty", "in_value", "sold_qty", "sold_value", "waste_qty",
                                                   "waste_value", "return_qty")}
    return ToolOutput({"start": s.isoformat(), "end": e.isoformat(), "totals": totals, "rows": rows[-31:],
                       "note": "use group_by=week for long ranges" if len(rows) > 31 else None})


@tool("get_sales_summary", "read", "Revenue, gross profit, units sold, demand lost to stockouts over time.",
      {"start": DATE, "end": DATE, "group_by": GROUP, "category": CATEGORY, "sku": SKU})
def _sales(ctx: ToolContext, start=None, end=None, group_by="week", category=None, sku=None) -> ToolOutput:
    s, e = reports.default_range(_d(start), _d(end))
    rows = reports.sales_series(ctx.db, s, e, group_by, category, sku)
    totals = {k: sum(r.get(k, 0) for r in rows) for k in ("qty", "revenue", "gross_profit", "lost_qty")}
    return ToolOutput({"start": s.isoformat(), "end": e.isoformat(), "totals": totals, "rows": rows[-31:],
                       "note": "use group_by=week for long ranges" if len(rows) > 31 else None})


@tool("get_cost_report", "read", "Cost & KPI report: waste cost/rate, stockout rate, lost margin, markdowns, supplier credits, inventory days, waste by category, top wasted SKUs. Default 30 days.",
      {"start": DATE, "end": DATE})
def _cost(ctx: ToolContext, start=None, end=None) -> ToolOutput:
    s, e = reports.default_range(_d(start), _d(end))
    return ToolOutput(reports.cost_report(ctx.db, s, e))


@tool("get_abc_xyz", "read", "ABC-XYZ analysis (90 days): 9-cell matrix. Pass cell (e.g. 'CZ') to list its SKUs.", {"cell": {"type": "string"}})
def _abc(ctx: ToolContext, cell: str | None = None) -> ToolOutput:
    r = reports.abc_xyz_report(ctx.db)
    items = [i for i in r["items"] if not cell or i["cell"] == cell.upper()]
    return ToolOutput({"matrix": r["matrix"], "items": items[:20], "items_total": len(items)})


@tool("get_delist_candidates", "read", "Delisting candidates (C-Y/C-Z, high waste or loss, not traffic drivers) with reasons and substitutes.")
def _delist_cands(ctx: ToolContext) -> ToolOutput:
    return ToolOutput(reports.delist_report(ctx.db))


@tool("list_suppliers", "read", "Suppliers: order days, lead time, minimum order, near-expiry return terms.")
def _suppliers(ctx: ToolContext) -> ToolOutput:
    sups = ctx.db.scalars(select(Supplier).options(joinedload(Supplier.agreements)).order_by(Supplier.code)).unique()
    wd = replenish.WEEKDAY_NAMES
    return ToolOutput([{
        "code": s.code, "name": s.name, "email": s.email, "lead_time_days": s.lead_time_days,
        "order_days": [wd[i] for i in s.order_weekdays], "min_order_value": s.min_order_value,
        "accepts_near_expiry_return": s.agreements[0].accepts_near_expiry_return if s.agreements else False,
        "return_min_days_before_expiry": s.agreements[0].return_min_days_before_expiry if s.agreements else None,
        "return_credit_pct": s.agreements[0].return_credit_pct if s.agreements else None,
    } for s in sups])


@tool("preview_reorder", "read", "PREVIEW suggested order quantities for one supplier (does not create a proposal).", {"supplier": {"type": "string", "description": "code (NCC01) or name"}},
      ["supplier"])
def _preview(ctx: ToolContext, supplier: str) -> ToolOutput:
    sup = replenish.get_supplier(ctx.db, supplier)
    if not sup:
        return ToolOutput({"error": f"Không tìm thấy nhà cung cấp '{supplier}'"})
    s = replenish.suggest_po(ctx.db, sup)
    s["lines"] = [{k: l[k] for k in ("sku", "name", "qty", "on_hand", "forecast_cover", "line_value", "abc_xyz")}
                  | {"mode": l["explain"]["mode"], "capped_by_shelf_life": l["explain"]["capped_by_shelf_life"]}
                  for l in s["lines"]]
    ui = [W.table(f"Dự kiến đặt {sup.name} (chỉ xem trước, chưa tạo đề xuất)", [
        W.col("name", "Hàng"), W.col("qty", "SL đặt", "num"), W.col("on_hand", "Tồn", "num"),
        W.col("forecast_cover", "Dự báo phủ", "num"), W.col("line_value", "Thành tiền", "money"),
        W.col("abc_xyz", "ABC-XYZ")], s["lines"])]
    return ToolOutput(s, ui=ui)


@tool("list_proposals", "read", "List proposals by status (PENDING, EXECUTED, REJECTED, ...).",
      {"status": {"type": "string", "default": "PENDING"}, "type": {"type": "string"}})
def _list_props(ctx: ToolContext, status: str = "PENDING", type: str | None = None) -> ToolOutput:
    q = select(Proposal).where(Proposal.status == status.upper()).order_by(Proposal.id.desc()).limit(20)
    if type:
        q = q.where(Proposal.type == type.upper())
    rows = [{"id": p.id, "type": p.type, "status": p.status, "title": p.title, "est_value": p.est_value,
             "created_at": p.created_at.isoformat(), "decided_by": p.decided_by,
             "decision_note": p.decision_note} for p in ctx.db.scalars(q)]
    ui = [W.table(f"Đề xuất ({status.upper()})", [
        W.col("id", "#", "num"), W.col("type", "Loại", "ptype"), W.col("title", "Nội dung"),
        W.col("est_value", "Giá trị", "money"), W.col("created_at", "Tạo lúc", "date")], rows,
        empty="Không có đề xuất nào.")]
    return ToolOutput(rows, ui=ui)


@tool("get_kpi_dashboard", "read", "KPIs of the last N days vs the previous N days, plus how often the manager accepted agent proposals.", {"days": {"type": "integer", "default": 30}})
def _kpi(ctx: ToolContext, days: int = 30) -> ToolOutput:
    r = reports.kpi_compare(ctx.db, days)
    keep = ("revenue", "gross_profit", "waste_cost", "waste_rate", "oos_rate", "lost_margin", "markdown_loss",
            "return_credit", "inventory_days")
    cur, prev = r["current"]["kpi"], r["previous"]["kpi"]
    ui = [W.kpis(f"KPI {days} ngày gần nhất so với {days} ngày trước", [
        W.kpi("Doanh thu", cur["revenue"], "money", prev["revenue"]),
        W.kpi("Lợi nhuận gộp", cur["gross_profit"], "money", prev["gross_profit"]),
        W.kpi("Chi phí hủy", cur["waste_cost"], "money", prev["waste_cost"], True),
        W.kpi("Tỷ lệ hủy", cur["waste_rate"], "pct", prev["waste_rate"], True),
        W.kpi("Tỷ lệ hết hàng", cur["oos_rate"], "pct", prev["oos_rate"], True),
        W.kpi("Ngày tồn kho", cur["inventory_days"], "num", prev["inventory_days"], True),
    ], note=f"{r['current']['start']} → {r['current']['end']}")]
    return ToolOutput({
        "current": {"start": r["current"]["start"], "end": r["current"]["end"],
                    **{k: r["current"]["kpi"][k] for k in keep}},
        "previous": {"start": r["previous"]["start"], "end": r["previous"]["end"],
                     **{k: r["previous"]["kpi"][k] for k in keep}},
        "agent_acceptance": acceptance_stats(ctx.db),
    }, ui=ui)


@tool("open_receive_form", "read", "Show the goods-receipt FORM in the chat for one purchase order awaiting delivery (status SENT). Staff fill actual qty + expiry and press confirm in the UI. This only displays the form; it records nothing.",
      {"po": {"type": "string", "description": "PO code (e.g. PO-20261107-NCC01) or numeric id"}}, ["po"])
def _open_receive_form(ctx: ToolContext, po: str) -> ToolOutput:
    ref = str(po).strip()
    q = select(PurchaseOrder).options(joinedload(PurchaseOrder.supplier))
    found = ctx.db.scalar(q.where(PurchaseOrder.id == int(ref))) if ref.isdigit() else None
    found = found or ctx.db.scalar(q.where(func.upper(PurchaseOrder.code) == ref.upper()))
    if not found:
        return ToolOutput({"error": f"Không tìm thấy đơn hàng '{po}'"})
    if found.status != "SENT":
        return ToolOutput({"error": f"Đơn {found.code} đang ở trạng thái {found.status}, không còn chờ giao nên không nhận hàng được."})
    lines = [{"line_id": l.id, "sku": l.product.sku, "name": l.product.name, "qty": l.qty,
              "received_qty": l.received_qty, "default_expiry": default_expiry(l.product.shelf_life_days).isoformat()}
             for l in found.lines]
    form = W.form("receive_po", f"Nhận hàng {found.code} · {found.supplier.name}", lines,
                  {"method": "POST", "path": f"/purchase-orders/{found.id}/receive"},
                  note="Ghi hạn sử dụng in trên bao bì cho từng lô (ô HSD điền sẵn theo hạn chuẩn, hãy sửa nếu khác).",
                  meta={"po_id": found.id, "code": found.code, "supplier": found.supplier.name,
                        "expected_date": found.expected_date.isoformat()})
    # Chi tra tom tat cho LLM; form day du chi di theo kenh UI
    return ToolOutput({"form_shown": True, "po": found.code, "supplier": found.supplier.name, "lines": len(lines),
                       "message": "Đã hiện form nhận hàng trong chat. Nhân viên điền số lượng và HSD rồi bấm xác nhận; "
                                  "chưa có hàng nào được nhận."}, ui=[form])


@tool("open_stock_count_form", "read", "Show a blind stock-count FORM in the chat for one category. Staff type what they counted and press confirm in the UI; any difference becomes a proposal for the manager. This only displays the form.",
      {"category": CATEGORY}, ["category"])
def _open_count_form(ctx: ToolContext, category: str) -> ToolOutput:
    lines = stockcount.sheet(ctx.db, category)
    if not lines:
        return ToolOutput({"error": f"Không tìm thấy nhóm hàng '{category}'"})
    form = W.form("stock_count", f"Kiểm kê: {category}", lines, {"method": "POST", "path": "/stock-counts"},
                  note="Ghi số đếm thực tế trên kệ và trong kho. Dòng để trống là chưa đếm.", meta={"category": category})
    return ToolOutput({"form_shown": True, "category": category, "lines": len(lines),
                       "message": "Đã hiện form kiểm kê trong chat. Nhân viên điền số đếm rồi bấm xác nhận; tồn kho chưa thay đổi."},
                      ui=[form])


# ---------------- CHART ----------------
@tool("build_chart", "read", "Render a chart in the UI (stock_flow/_value: in vs out; sales: revenue & profit; sales_qty: sold vs lost; waste_by_category; waste_trend; inventory_by_category; expiry_risk; abc_xyz). Default last 30 days.",
      {"metric": {"type": "string", "enum": list(charts.METRICS)}, "start": DATE, "end": DATE, "group_by": GROUP,
       "category": CATEGORY, "sku": SKU}, ["metric"])
def _chart(ctx: ToolContext, metric: str, start=None, end=None, group_by="day", category=None, sku=None) -> ToolOutput:
    spec = charts.build_chart(ctx.db, metric, _d(start), _d(end), group_by or "day", category, sku)
    data = spec.get("data", [])
    summary = {"chart_rendered": True, "title": spec["title"], "period": spec["period"], "rows": len(data)}
    for s in spec.get("series", []):
        vals = [r.get(s["key"], 0) or 0 for r in data]
        if vals:
            summary[s["key"]] = {"total": round(sum(vals)), "max": max(vals), "min": min(vals)}
    if len(data) <= 20:
        summary["data"] = data
    return ToolOutput(summary, ui=[{"type": "chart", "spec": spec}])


# ---------------- PROPOSE (chi tao de xuat PENDING) ----------------
def _prop_out(p, created: bool, extra: dict | None = None) -> ToolOutput:
    d = to_dict(p)
    msg = "Đã tạo đề xuất mới" if created else "Đề xuất tương tự đã tồn tại, dùng lại đề xuất cũ"
    return ToolOutput({"proposal_id": p.id, "status": p.status, "title": p.title, "est_value": p.est_value,
                       "message": f"{msg}. Cần Store Manager duyệt trong Hộp duyệt.", **(extra or {})},
                      ui=[{"type": "proposal", "proposal": d}])


@tool("propose_purchase_order", "propose", "Create a purchase-order PROPOSAL for one supplier. Nothing is sent until the manager approves.",
      {"supplier": {"type": "string", "description": "code (NCC01) or name"}}, ["supplier"])
def _propose_po(ctx: ToolContext, supplier: str) -> ToolOutput:
    sup = replenish.get_supplier(ctx.db, supplier)
    if not sup:
        return ToolOutput({"error": f"Không tìm thấy nhà cung cấp '{supplier}'"})
    p, created, sug = builders.purchase_order(ctx.db, sup, "agent", ctx.chat_session_id)
    ctx.db.commit()
    if not p:
        return ToolOutput({"message": f"Không cần đặt hàng {sup.name} lúc này: tồn còn hạn + hàng đang về đủ phủ "
                                      "nhu cầu dự báo.", "warnings": sug["warnings"]})
    return _prop_out(p, created, {"warnings": sug["warnings"]})


@tool("propose_markdown", "propose", "Create a markdown PROPOSAL for near-expiry lots where markdown is the best option. Optional lot_ids.",
      {"lot_ids": {"type": "array", "items": {"type": "integer"}}, "days": {"type": "integer", "default": 3}})
def _propose_md(ctx: ToolContext, lot_ids: list[int] | None = None, days: int = 3) -> ToolOutput:
    p, created = builders.markdown(ctx.db, "agent", lot_ids=lot_ids, days=max(days, 7 if lot_ids else days),
                                   chat_session_id=ctx.chat_session_id)
    ctx.db.commit()
    if not p:
        return ToolOutput({"message": "Không có lô nào mà giảm giá có lợi hơn giữ nguyên."})
    return _prop_out(p, created)


@tool("propose_supplier_return", "propose", "Create a return-to-supplier PROPOSAL for near-expiry lots (only if the contract allows). Optional lot_ids.",
      {"lot_ids": {"type": "array", "items": {"type": "integer"}}})
def _propose_return(ctx: ToolContext, lot_ids: list[int] | None = None) -> ToolOutput:
    res = builders.supplier_return(ctx.db, "agent", lot_ids=lot_ids, chat_session_id=ctx.chat_session_id)
    ctx.db.commit()
    if not res:
        return ToolOutput({"message": "Không có lô nào nên trả NCC (không có điều khoản hoặc giảm giá/giữ có lợi hơn)."})
    outs = [_prop_out(p, c) for p, c in res]
    return ToolOutput([o.data for o in outs], ui=[u for o in outs for u in o.ui])


@tool("propose_dispose_expired", "propose", "Create a PROPOSAL to write off expired lots still in stock.")
def _propose_dispose(ctx: ToolContext) -> ToolOutput:
    p, created = builders.dispose_expired(ctx.db, "agent", ctx.chat_session_id)
    ctx.db.commit()
    if not p:
        return ToolOutput({"message": "Không có lô nào đã quá hạn còn trong kho."})
    return _prop_out(p, created)


@tool("propose_delist", "propose", "Create a delisting PROPOSAL for one SKU (only if it is a delisting candidate).",
      {"sku": SKU}, ["sku"])
def _propose_delist(ctx: ToolContext, sku: str) -> ToolOutput:
    p, created, err = builders.delist(ctx.db, sku, "agent", ctx.chat_session_id)
    ctx.db.commit()
    if not p:
        return ToolOutput({"error": err})
    return _prop_out(p, created)


@tool("revise_proposal", "propose", "Revise a PENDING proposal when the user asks to change it (e.g. 'giảm còn 30 thùng', 'giảm giá 30% thôi'). Creates a NEW pending proposal and marks the old one superseded; the manager must still approve. Only PENDING purchase orders (sku_qty: new qty per SKU) and markdowns (markdown_pct: 0.3 = 30%).",
      {"proposal_id": {"type": "integer"},
       "sku_qty": {"type": "array", "description": "purchase orders: new quantity per SKU",
                   "items": {"type": "object", "properties": {"sku": {"type": "string"}, "qty": {"type": "integer"}},
                             "required": ["sku", "qty"]}},
       "markdown_pct": {"type": "number", "description": "markdowns: new discount, 0.3 = 30%"}}, ["proposal_id"])
def _revise(ctx: ToolContext, proposal_id: int, sku_qty: list[dict] | None = None,
            markdown_pct: float | None = None) -> ToolOutput:
    try:
        p = builders.revise(ctx.db, int(proposal_id), "agent", {str(x["sku"]): int(x["qty"]) for x in sku_qty or []},
                            markdown_pct, ctx.chat_session_id)
    except (builders.ReviseError, KeyError, TypeError, ValueError) as e:
        ctx.db.rollback()
        return ToolOutput({"error": str(e)})
    ctx.db.commit()
    return _prop_out(p, True, {"replaces": proposal_id})


@tool("propose_demand_hypothesis", "propose", "Record the manager's belief about future demand (event, weather, promotion) as a PROPOSAL. Use ONLY the factor and dates the user stated; if either is missing, ask first. Set exactly one of category or sku. Forecasts change only after approval.",
      {"factor": {"type": "number", "description": "demand multiplier stated by the user, 1.5 = +50%, 0.7 = -30%"},
       "start_date": DATE, "end_date": DATE, "reason": {"type": "string", "description": "the user's reason, in Vietnamese"},
       "category": CATEGORY, "sku": SKU}, ["factor", "start_date", "end_date", "reason"])
def _propose_hypothesis(ctx: ToolContext, factor: float, start_date: str, end_date: str, reason: str,
                        category: str | None = None, sku: str | None = None) -> ToolOutput:
    try:
        p, created = builders.demand_hypothesis(ctx.db, "agent", float(factor), date.fromisoformat(start_date),
                                                date.fromisoformat(end_date), reason, category, sku, ctx.chat_session_id)
    except (hypotheses.HypothesisError, ValueError) as e:
        ctx.db.rollback()
        return ToolOutput({"error": str(e)})
    ctx.db.commit()
    return _prop_out(p, created, {k: p.payload[k] for k in ("baseline_total", "adjusted_total", "sku_count")})


@tool("list_demand_hypotheses", "read", "The manager's demand hypotheses: active ones and how past ones turned out (correct / partly / wrong).")
def _list_hypotheses(ctx: ToolContext) -> ToolOutput:
    rows = hypotheses.list_views(ctx.db)
    ui = [W.table("Giả thuyết nhu cầu", [
        W.col("scope", "Phạm vi"), W.col("factor", "Hệ số", "num"), W.col("start_date", "Từ", "date"),
        W.col("end_date", "Đến", "date"), W.col("reason", "Lý do"), W.col("verdict_label", "Kết quả")], rows,
        empty="Chưa có giả thuyết nào.")]
    return ToolOutput(rows, ui=ui)


@tool("get_order_edit_patterns", "read", "Consistent habits in how the manager edits suggested order quantities, by category, plus learned adjustments already active.")
def _edit_patterns(ctx: ToolContext) -> ToolOutput:
    found = learning.patterns(ctx.db)
    active = [{"category": a.category, "factor": a.factor} for a in learning.active_adjustments(ctx.db).values()]
    ui = [W.table("Thói quen sửa số lượng đặt", [
        W.col("category", "Nhóm"), W.col("edits", "Lần sửa", "num"), W.col("proposals", "Số đơn", "num"),
        W.col("factor", "Hệ số gợi ý", "num")], found, empty="Chưa đủ lịch sử sửa để thấy thói quen rõ ràng.")]
    return ToolOutput({"patterns": found, "active_adjustments": active}, ui=ui)


@tool("propose_order_adjustment", "propose", "Create a PROPOSAL to apply a learned order-quantity factor to one category. Refused unless the edit history supports it; the factor is computed, never chosen by you.",
      {"category": CATEGORY}, ["category"])
def _propose_adjustment(ctx: ToolContext, category: str) -> ToolOutput:
    p, created, err = builders.order_adjustment(ctx.db, category, "agent", ctx.chat_session_id)
    ctx.db.commit()
    if not p:
        return ToolOutput({"error": err})
    return _prop_out(p, created)


def schemas() -> list[dict]:
    return [t.schema() for t in REGISTRY.values()]
