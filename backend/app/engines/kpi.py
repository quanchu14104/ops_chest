"""Dinh nghia KPI dung chung cho dashboard, bao cao chi phi va backtest."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class KpiTotals:
    days: int
    revenue: float = 0.0
    cogs: float = 0.0  # gia von hang da ban
    units_sold: float = 0.0
    units_lost: float = 0.0  # nhu cau khong dap ung do het hang
    lost_margin: float = 0.0
    waste_units: float = 0.0
    waste_cost: float = 0.0
    markdown_loss: float = 0.0
    return_credit: float = 0.0
    return_cost: float = 0.0  # gia von hang da tra NCC
    avg_inventory_value: float = 0.0
    purchases_value: float = 0.0


def summarize(t: KpiTotals) -> dict:
    waste_rate = t.waste_cost / (t.cogs + t.waste_cost) if (t.cogs + t.waste_cost) else 0.0
    oos_rate = t.units_lost / (t.units_sold + t.units_lost) if (t.units_sold + t.units_lost) else 0.0
    daily_cogs = t.cogs / t.days if t.days else 0.0
    inv_days = t.avg_inventory_value / daily_cogs if daily_cogs else 0.0
    gross_profit = t.revenue - t.cogs - t.waste_cost - t.return_cost + t.return_credit
    d = asdict(t)
    d.update(
        waste_rate=round(waste_rate, 4),
        oos_rate=round(oos_rate, 4),
        inventory_days=round(inv_days, 2),
        gross_profit=round(gross_profit),
        gross_margin_pct=round(gross_profit / t.revenue, 4) if t.revenue else 0.0,
    )
    for k in ("revenue", "cogs", "lost_margin", "waste_cost", "markdown_loss", "return_credit",
              "return_cost", "avg_inventory_value", "purchases_value"):
        d[k] = round(d[k])
    return d
