"""Backtest A/B: cung mot cua hang, cung nhu cau (tat dinh), hai chinh sach dat hang khac nhau.

    uv run python -m app.sim.backtest --days 90
    uv run python -m app.sim.backtest --start 2026-01-20 --days 60   # giai doan Tet
    uv run python -m app.sim.backtest --sensitivity                  # ghi lai bang do nhay cho giao dien

Mac dinh so voi doi thu cong bang (A co giam gia gio vang) trong the gioi ma khach chi phan ung bang mot
nua muc engine gia dinh. Hai chinh sach deu bat dau tu cung trang thai sau giai doan khoi dong.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from app.engines.abc_xyz import SkuStats, classify
from app.engines.kpi import summarize
from app.sim.catalog import build_catalog
from app.sim.policies import BaselineGoldenHourPolicy, BaselinePolicy, OpsChestPolicy
from app.sim.store_sim import Policy, StoreSim
from app.sim.world import OPTIMISTIC_WORLD, PESSIMISTIC_WORLD, REFERENCE_WORLD, WorldParams

WARMUP_DAYS = 200
SENSITIVITY_FILE = Path(__file__).parent / "data" / "sensitivity.json"
SENSITIVITY_START = date(2026, 9, 8)
SENSITIVITY_DAYS = 60


def initial_stock(sim: StoreSim, start: date) -> None:
    for p in sim.products:
        qty = max(p.pack_size, int(p.base_rate * min(p.shelf_life_days, 4) + 0.5))
        sim.add_lot(p.sku, qty, start - timedelta(days=1), p.unit_cost)


def warm_base(start: date, seed: int = 7, warmup: int = WARMUP_DAYS) -> StoreSim:
    """Cua hang truoc ky so sanh, luon van hanh bang chinh sach goc de moi kich ban cung diem xuat phat."""
    suppliers, products = build_catalog()
    base = StoreSim(suppliers, products, seed=seed)
    warm_start = start - timedelta(days=warmup)
    initial_stock(base, warm_start)
    base.run(warm_start, warmup, BaselinePolicy())
    return base


def _class_a(base: StoreSim, lookback: int = 90) -> set[str]:
    """Nhom A (theo loi nhuan 90 ngay truoc ky so sanh), co dinh cho ca hai chinh sach de so cung mot tap SKU."""
    stats = []
    for p in base.products:
        h = base.hist[p.sku]
        sales = h["sales"][-lookback:]
        if not sales:
            continue
        margin = sum(h["revenue"][-lookback:]) - sum(h["cogs"][-lookback:]) - sum(h["waste_cost"][-lookback:])
        weekly = [sum(sales[i:i + 7]) for i in range(len(sales) % 7, len(sales), 7)]
        stats.append(SkuStats(p.sku, p.name, margin, weekly))
    return {k for k, v in classify(stats).items() if v.cell[0] == "A"} if stats else set()


def _role_breakdown(sim: StoreSim, days: int, class_a: set[str]) -> dict:
    """Ty le het hang theo vai tro (hang keo khach, nhom A) va het hang CAP NHOM cua hang tuoi:
    ngay ma moi SKU trong nhom deu het hang (khach khong con mon thay the). Chi do, chua doi cach dat."""
    def rate(skus):
        sold = sum(sum(sim.hist[s]["sales"][-days:]) for s in skus)
        lost = sum(sum(sim.hist[s]["lost"][-days:]) for s in skus)
        return round(lost / (sold + lost), 4) if sold + lost else 0.0
    traffic = [p.sku for p in sim.products if p.is_traffic_driver]
    groups = defaultdict(list)
    for p in sim.products:
        if p.freshness_class == "FRESH":
            groups[p.category].append(p.sku)
    empty = total = 0
    for skus in groups.values():
        for k in range(1, days + 1):
            total += 1
            empty += all(sim.hist[s]["lost"][-k] > 0 for s in skus)
    return {"oos_traffic": rate(traffic), "oos_class_a": rate(sorted(class_a)),
            "group_oos_fresh": round(empty / total, 4) if total else 0.0}


def compare(base: StoreSim, start: date, days: int, world: WorldParams = REFERENCE_WORLD,
            baseline: Policy | None = None, ops: OpsChestPolicy | None = None) -> dict:
    results = {}
    by_class = {}
    class_a = _class_a(base)
    for policy in (baseline or BaselineGoldenHourPolicy(), ops or OpsChestPolicy()):
        sim = copy.deepcopy(base)
        sim.world = world
        sim.reset_totals()
        t0 = time.perf_counter()
        sim.run(start, days, policy)
        k = summarize(sim.totals)
        k["runtime_s"] = round(time.perf_counter() - t0, 1)
        if isinstance(policy, OpsChestPolicy):
            k["actions"] = policy.actions
        k.update(_role_breakdown(sim, days, class_a))
        results[policy.name] = k
        by_class[policy.name] = _class_breakdown(sim, days)
    a, b = list(results.values())
    delta = {
        "waste_cost_saved": a["waste_cost"] - b["waste_cost"],
        "lost_margin_saved": a["lost_margin"] - b["lost_margin"],
        "gross_profit_gain": b["gross_profit"] - a["gross_profit"],
        "inventory_value_reduction": a["avg_inventory_value"] - b["avg_inventory_value"],
    }
    return {"start": start.isoformat(), "days": days, "seed": base.seed, "results": results,
            "by_freshness": by_class, "delta": delta}


def run_backtest(start: date, days: int, seed: int = 7, warmup: int = WARMUP_DAYS,
                 world: WorldParams = REFERENCE_WORLD, baseline: Policy | None = None,
                 ops: OpsChestPolicy | None = None) -> dict:
    return compare(warm_base(start, seed, warmup), start, days, world, baseline, ops)


def _row(key: str, label: str, note: str, res: dict) -> dict:
    a, b = list(res["results"].values())
    return {
        "key": key, "label": label, "note": note, "seed": res["seed"],
        "gain": round(b["gross_profit"] - a["gross_profit"]),
        "gain_pct": round(b["gross_profit"] / a["gross_profit"] - 1, 4),
        "waste_a": a["waste_rate"], "waste_b": b["waste_rate"],
        "oos_a": a["oos_rate"], "oos_b": b["oos_rate"],
        "oos_traffic_a": a["oos_traffic"], "oos_traffic_b": b["oos_traffic"],
        "oos_class_a_a": a["oos_class_a"], "oos_class_a_b": b["oos_class_a"],
        "group_oos_fresh_a": a["group_oos_fresh"], "group_oos_fresh_b": b["group_oos_fresh"],
    }


def run_sensitivity(start: date = SENSITIVITY_START, days: int = SENSITIVITY_DAYS) -> dict:
    """Moi kich ban chi doi MOT dieu so voi kich ban tham chieu."""
    base = warm_base(start, 7)
    rows = [
        _row("reference", "Tham chiếu", "A có giờ vàng, khách phản ứng bằng 50% giả định của engine",
             compare(base, start, days)),
        _row("no_floor", "B không có sàn mức phục vụ", "Cách đặt cũ: newsvendor được để thiếu hàng tới 70% số ngày",
             compare(base, start, days, ops=OpsChestPolicy(service_floors=False))),
        _row("daypart_flat", "Giờ giảm giá cố định 18h cho mọi nhóm", "Cách cũ: giờ vàng 18h, giả định 30% khách cho mọi nhóm",
             compare(base, start, days, ops=OpsChestPolicy(dayparts=False))),
        _row("floor_a80", "Sàn nhóm A 80% (thay vì 90%)", "Đánh đổi: hết hàng nhích lên, hủy giảm",
             compare(base, start, days, ops=OpsChestPolicy(floors={"traffic": 0.95, "A": 0.80, "other": 0.50}))),
    ]
    for seed in (11, 23):
        rows.append(_row(f"seed_{seed}", f"Nhu cầu khác (seed {seed})", "Đổi chuỗi nhu cầu ngẫu nhiên",
                         compare(warm_base(start, seed), start, days)))
    rows += [
        _row("world_100", "Khách phản ứng đúng 100% giả định", "Trường hợp tốt nhất cho giảm giá của B",
             compare(base, start, days, world=OPTIMISTIC_WORLD)),
        _row("world_25", "Khách chỉ phản ứng 25% giả định", "Engine đánh giá quá cao tác dụng của giảm giá",
             compare(base, start, days, world=PESSIMISTIC_WORLD)),
        _row("order_only", "B chỉ đặt hàng", "Tắt giảm giá và trả NCC của B: đo riêng phần công của đặt hàng",
             compare(base, start, days, ops=OpsChestPolicy(dispose=False))),
        _row("no_demand_fix", "B không tách doanh số giảm giá", "Dự báo tính cả lượng bán nhờ giảm giá vào nhu cầu",
             compare(base, start, days, ops=OpsChestPolicy(adjust_markdown=False))),
        _row("approve_80", "Store Manager duyệt 80%", "Đơn không được duyệt thì SM tự đặt theo kinh nghiệm, giảm giá thì bỏ qua",
             compare(base, start, days, ops=OpsChestPolicy(approval_rate=0.8))),
        _row("approve_60", "Store Manager duyệt 60%", "Đơn không được duyệt thì SM tự đặt theo kinh nghiệm, giảm giá thì bỏ qua",
             compare(base, start, days, ops=OpsChestPolicy(approval_rate=0.6))),
        _row("fefo_80", "20% lượt mua lấy lô mới", "Khách lấy hàng phía sau kệ; engine vẫn tin là bán FEFO",
             compare(base, start, days, world=REFERENCE_WORLD.with_fefo(0.8))),
        _row("fefo_50", "50% lượt mua lấy lô mới", "Khách lấy hàng phía sau kệ; engine vẫn tin là bán FEFO",
             compare(base, start, days, world=REFERENCE_WORLD.with_fefo(0.5))),
        _row("legacy", "Cách so sánh cũ", "A không giảm giá gì, khách phản ứng đúng giả định: thiên vị cho B",
             compare(base, start, days, world=OPTIMISTIC_WORLD, baseline=BaselinePolicy())),
    ]
    return {"start": start.isoformat(), "days": days, "rows": rows}


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
            ("oos_rate", "Tỷ lệ hết hàng", "{:.2%}"), ("oos_traffic", "Hết hàng: kéo khách", "{:.2%}"),
            ("oos_class_a", "Hết hàng: nhóm A", "{:.2%}"), ("group_oos_fresh", "Cả nhóm tươi trống", "{:.2%}"),
            ("lost_margin", "Lãi mất do hết hàng", "{:,.0f}"),
            ("markdown_loss", "Giảm giá đã chi", "{:,.0f}"), ("return_credit", "NCC hoàn tiền", "{:,.0f}"),
            ("avg_inventory_value", "Tồn kho TB (giá vốn)", "{:,.0f}"), ("inventory_days", "Số ngày tồn", "{:.1f}")]
    names = list(results)
    lines = [f"{'Chỉ số':<24}" + "".join(f"{n:>32}" for n in names)]
    for k, label, f in keys:
        lines.append(f"{label:<24}" + "".join(f"{f.format(results[n][k]):>32}" for n in names))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=None)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sensitivity", action="store_true", help=f"Chạy các kịch bản và ghi vào {SENSITIVITY_FILE.name}")
    args = ap.parse_args()
    if args.sensitivity:
        out = run_sensitivity()
        SENSITIVITY_FILE.parent.mkdir(exist_ok=True)
        SENSITIVITY_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        for r in out["rows"]:
            print(f"{r['key']:<14} {r['gain_pct']:+7.1%}  hủy {r['waste_a']:.1%}/{r['waste_b']:.1%}"
                  f"  hết hàng {r['oos_a']:.1%}/{r['oos_b']:.1%}"
                  f"  kéo khách {r['oos_traffic_a']:.1%}/{r['oos_traffic_b']:.1%}"
                  f"  nhóm A {r['oos_class_a_a']:.1%}/{r['oos_class_a_b']:.1%}"
                  f"  cả nhóm tươi trống {r['group_oos_fresh_a']:.1%}/{r['group_oos_fresh_b']:.1%}")
        return
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
