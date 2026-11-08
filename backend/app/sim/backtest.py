"""Backtest A/B: cung mot cua hang, cung nhu cau (tat dinh), hai chinh sach dat hang khac nhau.

    uv run python -m app.sim.backtest --days 90
    uv run python -m app.sim.backtest --start 2026-01-20 --days 60   # giai doan Tet
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import defaultdict
from datetime import date, timedelta

from app.engines.kpi import summarize
from app.sim.catalog import build_catalog
from app.sim.policies import BaselinePolicy, OpsChestPolicy
from app.sim.store_sim import StoreSim

WARMUP_DAYS = 200


def initial_stock(sim: StoreSim, start: date) -> None:
    for p in sim.products:
        qty = max(p.pack_size, int(p.base_rate * min(p.shelf_life_days, 4) + 0.5))
        sim.add_lot(p.sku, qty, start - timedelta(days=1), p.unit_cost)


def run_backtest(start: date, days: int, seed: int = 7, warmup: int = WARMUP_DAYS) -> dict:
    suppliers, products = build_catalog()
    base = StoreSim(suppliers, products, seed=seed)
    warm_start = start - timedelta(days=warmup)
    initial_stock(base, warm_start)
    base.run(warm_start, warmup, BaselinePolicy())

    results = {}
    by_class = {}
    for policy in (BaselinePolicy(), OpsChestPolicy()):
        sim = copy.deepcopy(base)
        sim.reset_totals()
        t0 = time.perf_counter()
        sim.run(start, days, policy)
        k = summarize(sim.totals)
        k["runtime_s"] = round(time.perf_counter() - t0, 1)
        if isinstance(policy, OpsChestPolicy):
            k["actions"] = policy.actions
        results[policy.name] = k
        by_class[policy.name] = _class_breakdown(sim, days)
    a, b = list(results.values())
    delta = {
        "waste_cost_saved": a["waste_cost"] - b["waste_cost"],
        "lost_margin_saved": a["lost_margin"] - b["lost_margin"],
        "gross_profit_gain": b["gross_profit"] - a["gross_profit"],
        "inventory_value_reduction": a["avg_inventory_value"] - b["avg_inventory_value"],
    }
    return {"start": start.isoformat(), "days": days, "seed": seed, "results": results,
            "by_freshness": by_class, "delta": delta}


def _class_breakdown(sim: StoreSim, days: int) -> dict:
    agg = defaultdict(lambda: defaultdict(float))
    for p in sim.products:
        h = sim.hist[p.sku]
        g = agg[p.freshness_class]
        g["revenue"] += sum(h["revenue"][-days:])
        g["cogs"] += sum(h["cogs"][-days:])
        g["waste_cost"] += sum(h["waste_cost"][-days:])
        g["sold"] += sum(h["sales"][-days:])
        g["lost"] += sum(h["lost"][-days:])
    out = {}
    for k, g in agg.items():
        out[k] = {
            "waste_rate": round(g["waste_cost"] / (g["cogs"] + g["waste_cost"]), 4) if g["cogs"] else 0,
            "oos_rate": round(g["lost"] / (g["sold"] + g["lost"]), 4) if g["sold"] else 0,
            "revenue": round(g["revenue"]),
        }
    return out


def _fmt(results: dict) -> str:
    keys = [("revenue", "Doanh thu", "{:,.0f}"), ("gross_profit", "Lợi nhuận gộp", "{:,.0f}"),
            ("waste_cost", "Giá vốn hàng hủy", "{:,.0f}"), ("waste_rate", "Tỷ lệ hủy", "{:.2%}"),
            ("oos_rate", "Tỷ lệ hết hàng", "{:.2%}"), ("lost_margin", "Lãi mất do hết hàng", "{:,.0f}"),
            ("markdown_loss", "Giảm giá đã chi", "{:,.0f}"), ("return_credit", "NCC hoàn tiền", "{:,.0f}"),
            ("avg_inventory_value", "Tồn kho TB (giá vốn)", "{:,.0f}"), ("inventory_days", "Số ngày tồn", "{:.1f}")]
    names = list(results)
    lines = [f"{'Chỉ số':<24}" + "".join(f"{n:>26}" for n in names)]
    for k, label, f in keys:
        lines.append(f"{label:<24}" + "".join(f"{f.format(results[n][k]):>26}" for n in names))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    from app.clock import today
    start = args.start or today() - timedelta(days=args.days)
    res = run_backtest(start, args.days, args.seed)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return
    print(f"Backtest {res['start']} + {args.days} ngày (seed={args.seed})\n")
    print(_fmt(res["results"]))
    print("\nTheo nhóm vòng đời:", json.dumps(res["by_freshness"], ensure_ascii=False, indent=1))
    print("\nChênh lệch (B so với A):", json.dumps(res["delta"], ensure_ascii=False))


if __name__ == "__main__":
    main()
