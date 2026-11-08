"""Tao chart spec JSON (khong ve). Frontend render bang Recharts. LLM chi chon metric + tham so."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.fmt import dmy
from app.services import inventory, reports

METRICS = {
    "stock_flow": "Hàng vào/ra kho (số lượng): nhập, bán, hủy, trả NCC",
    "stock_flow_value": "Hàng vào/ra kho theo giá vốn (VND)",
    "sales": "Doanh thu và lợi nhuận gộp",
    "sales_qty": "Số lượng bán và nhu cầu hụt do hết hàng",
    "waste_by_category": "Giá vốn hàng hủy theo nhóm hàng",
    "waste_trend": "Giá vốn hàng hủy theo thời gian",
    "inventory_by_category": "Giá trị tồn kho hiện tại theo nhóm hàng",
    "expiry_risk": "Giá trị hàng có nguy cơ hủy theo số ngày còn hạn",
    "abc_xyz": "Ma trận ABC-XYZ: số SKU và lợi nhuận 90 ngày mỗi ô",
}


def build_chart(db: Session, metric: str, start: date | None = None, end: date | None = None,
                group_by: str = "day", category: str | None = None, sku: str | None = None) -> dict:
    if metric not in METRICS:
        raise ValueError(f"metric không hỗ trợ: {metric}. Chọn một trong: {', '.join(METRICS)}")
    start, end = reports.default_range(start, end)
    scope = " · ".join(x for x in [category, sku] if x)
    period = f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"
    spec: dict = {"metric": metric, "period": period, "start": start.isoformat(), "end": end.isoformat()}

    if metric in ("stock_flow", "stock_flow_value"):
        rows = reports.stock_flow(db, start, end, group_by, category, sku)
        if metric == "stock_flow":
            series = [("in_qty", "Nhập"), ("sold_qty", "Bán"), ("waste_qty", "Hủy"), ("return_qty", "Trả NCC")]
            unit = "đơn vị"
        else:
            series = [("in_value", "Nhập"), ("sold_value", "Bán (giá vốn)"), ("waste_value", "Hủy")]
            unit = "VND"
        spec.update(type="bar", title=f"Hàng vào/ra kho {scope}".strip(), x_key="period", unit=unit,
                    series=[{"key": k, "label": l} for k, l in series], data=rows)
    elif metric in ("sales", "sales_qty"):
        rows = reports.sales_series(db, start, end, group_by, category, sku)
        if metric == "sales":
            spec.update(type="line", title=f"Doanh thu & lợi nhuận gộp {scope}".strip(), unit="VND",
                        series=[{"key": "revenue", "label": "Doanh thu"},
                                {"key": "gross_profit", "label": "Lợi nhuận gộp"}])
        else:
            spec.update(type="bar", stacked=True, title=f"Số lượng bán & nhu cầu hụt {scope}".strip(),
                        unit="đơn vị", series=[{"key": "qty", "label": "Đã bán"},
                                               {"key": "lost_qty", "label": "Hụt do hết hàng"}])
        spec.update(x_key="period", data=rows)
    elif metric == "waste_by_category":
        rep = reports.cost_report(db, start, end)
        spec.update(type="hbar", title="Giá vốn hàng hủy theo nhóm", x_key="category", unit="VND",
                    series=[{"key": "waste_value", "label": "Giá vốn hủy"}], data=rep["waste_by_category"])
    elif metric == "waste_trend":
        rows = reports.stock_flow(db, start, end, group_by, category, sku)
        spec.update(type="line", title=f"Hàng hủy theo thời gian {scope}".strip(), x_key="period", unit="VND",
                    series=[{"key": "waste_value", "label": "Giá vốn hủy"}], data=rows)
    elif metric == "inventory_by_category":
        s = inventory.inventory_summary(db)
        spec.update(type="hbar", title="Giá trị tồn kho theo nhóm (giá vốn)", x_key="category", unit="VND",
                    period=f"tại {dmy(s['as_of'])}", series=[{"key": "value", "label": "Giá trị tồn"}],
                    data=[{"category": c["category"], "value": c["value"]} for c in s["by_category"]])
    elif metric == "expiry_risk":
        e = inventory.expiring_lots(db, days=7, category=category, with_options=False)
        order = ["Đã quá hạn", "Hết hạn hôm nay", "1-3 ngày", "4-7 ngày"]
        data = sorted(e["summary"], key=lambda x: order.index(x["bucket"]) if x["bucket"] in order else 9)
        spec.update(type="bar", title="Giá trị hàng có nguy cơ hủy (7 ngày tới)", x_key="bucket", unit="VND",
                    period=f"tại {dmy(e['as_of'])}", series=[{"key": "value_at_risk", "label": "Giá vốn dự kiến hủy"}],
                    data=data)
    elif metric == "abc_xyz":
        rep = reports.abc_xyz_report(db)
        spec.update(type="matrix", title="Ma trận ABC-XYZ (90 ngày)", x_key="cell", unit="SKU",
                    period="90 ngày gần nhất", series=[{"key": "skus", "label": "Số SKU"},
                                                       {"key": "margin_90d", "label": "Lợi nhuận 90 ngày"}],
                    data=rep["matrix"])
    spec["row_count"] = len(spec.get("data", []))
    return spec
