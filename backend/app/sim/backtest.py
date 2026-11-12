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


# ------------------------------------------------------------------ FreshRetailNet-50K: nhieu diem ban, nhu cau that
FRN_FILE = Path(__file__).parent / "data" / "frn" / "backtest.json"


def frn_base(store_id: int, t0: int) -> tuple[StoreSim, list]:
    """Cua hang chay nhu cau that cua diem FRN `store_id`; khoi dong ngay 0..t0 bang chinh sach 'kinh nghiem'."""
    from app.sim import frn
    from app.sim.demand import FrnDemand
    from app.sim.frn_catalog import build_frn_catalog
    from app.sim.world import frn_world

    st, k = frn.store(store_id), frn.k_scale()
    suppliers, products = build_frn_catalog(st, k)
    base = StoreSim(suppliers, products, seed=store_id, demand=FrnDemand(st, k), world=frn_world(store_id))
    initial_stock(base, st.dates[0])
    base.run(st.dates[0], t0 + 1, BaselinePolicy())
    return base, st.dates


def _run(base: StoreSim, start: date, days: int, policy: Policy, class_a: set[str], world=None) -> dict:
    sim = copy.deepcopy(base)
    if world is not None:
        sim.world = world
    sim.reset_totals()
    sim.run(start, days, policy)
    k = summarize(sim.totals)
    k.update(_role_breakdown(sim, days, class_a))
    # Lai theo mat hang (giong _class_breakdown): dau vao cua bo chon theo lai
    k["sku_gp"] = {p.sku: sum(sim.hist[p.sku]["revenue"][-days:]) - sum(sim.hist[p.sku]["cogs"][-days:])
                   - sum(sim.hist[p.sku]["waste_cost"][-days:]) for p in sim.products}
    return k


FRN_SCENARIOS = {
    # key: (nhan, ghi chu, ham tao chinh sach B tu bo chon, he so phan ung cua khach so voi uoc luong FRN).
    # Moi kich ban dung bo chon B-gate cua diem do (hoc tren nua diem ban con lai: ngoai mau).
    "reference": ("Tham chiếu", "Khách phản ứng với giảm giá bằng 50% mức engine giả định (FRN không đo được độ co giãn đáng tin)", lambda g: OpsChestPolicy(ml_model="bt_", gate=g), 1.0),
    "world_50": ("Khách phản ứng bằng nửa tham chiếu", "25% mức engine giả định: giảm giá kém tác dụng hơn", lambda g: OpsChestPolicy(ml_model="bt_", gate=g), 0.5),
    "world_25": ("Khách phản ứng bằng 1/4 tham chiếu", "12,5% mức engine giả định: engine đánh giá quá cao giảm giá", lambda g: OpsChestPolicy(ml_model="bt_", gate=g), 0.25),
    "approve_80": ("Store Manager duyệt 80%", "Đơn không được duyệt thì SM tự đặt theo kinh nghiệm", lambda g: OpsChestPolicy(ml_model="bt_", gate=g, approval_rate=0.8), 1.0),
    "approve_60": ("Store Manager duyệt 60%", "Đơn không được duyệt thì SM tự đặt theo kinh nghiệm", lambda g: OpsChestPolicy(ml_model="bt_", gate=g, approval_rate=0.6), 1.0),
    "no_floor": ("B không có sàn mức phục vụ", "Newsvendor được để thiếu hàng", lambda g: OpsChestPolicy(ml_model="bt_", gate=g, service_floors=False), 1.0),
    "daypart_flat": ("Giờ giảm giá cố định 18h", "Không dùng khung giờ bán học từ FRN", lambda g: OpsChestPolicy(ml_model="bt_", gate=g, dayparts=False), 1.0),
    "order_only": ("B chỉ đặt hàng", "Tắt giảm giá và trả NCC: đo riêng phần đặt hàng", lambda g: OpsChestPolicy(ml_model="bt_", gate=g, dispose=False), 1.0),
}


def _pct(a: float, b: float) -> float:
    return round(b / a - 1, 4) if a else 0.0


def _summary(values: list[float]) -> dict:
    v = sorted(values)
    if not v:
        return {}

    def q(p):
        i = (len(v) - 1) * p
        lo, hi = int(i), min(int(i) + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (i - lo), 4)
    return {"median": q(0.5), "q25": q(0.25), "q75": q(0.75), "min": v[0], "max": v[-1], "n": len(v)}


# ---------------------------------------------------------------- bo chon theo LAI (decision gate)
# Bien the B tren moi diem FRN. "Tat ca" = LightGBM o moi mat hang du lich su (khong loc nhom): dung de do lai
# theo nhom. b_ml giu nguyen nghia cu (nhom trong meta.json, chon theo sai so du bao) de so voi lan chay truoc.
# Bien the ung vien cho bo chon: sigma doi xung (cu) / phan phoi lech q10-q50-q90 / du bao LightGBM + sigma EWMA
GATE_VARIANTS = ("sym", "split", "ewma_sigma")
GATE_SIZE_CUTS = (None, 30, 50, 75)  # bac quy mo diem ban (so mat hang FRN): khong chia / <=cut va >cut
ML_ALL = {"sym": "b_ml_all", "split": "b_ml_split", "ewma_sigma": "b_ml_mid_ewma_sigma"}
B_VARIANTS = ("b_ewma", "b_ml", "b_ml_all", "b_ml_split", "b_ml_mid_ewma_sigma", "b_gate")


def _short(v: str) -> str:
    return {"b_ewma": "ewma", "b_ml": "ml"}.get(v, v[2:])


def group_key(segment: str, store_size: int, size_cut: int | None) -> str:
    from app.ml.forecaster import store_tier

    return segment if size_cut is None else f"{segment}|{store_tier(store_size, size_cut)}"


def choose_gate(skus: list[dict], store_gp: dict[int, float], variants=GATE_VARIANTS, cuts=GATE_SIZE_CUTS) -> dict:
    """Chon bien the va tap nhom dung ML theo LAI tren cac diem trong `skus` (chi cac diem do).

    skus: moi dong {store_id, size, segment, gp: {"b_ewma": lai, "sym": lai, "split": lai, "ewma_sigma": lai}}:
    lai cua mat hang trong lan chay EWMA va lan chay LightGBM-tat-ca cua bien the. store_gp: lai B-EWMA cua ca diem ban.
    Gia tri mot nhom = tong (lai ML - lai EWMA) / lai B-EWMA cua diem: moi diem duoc tinh theo %, nen diem nho khong
    bi diem lon lan at (chi so bao cao la trung vi % theo diem). Nhom co gia tri > 0 thi dung ML.
    Chon (bien the, nguong quy mo) co tong gia tri cac nhom duoc chon lon nhat; hoa thi giu cach don gian hon
    (doi xung, khong chia quy mo) vi duoc thu truoc."""
    best = None
    candidates = []
    for v in variants:
        for cut in cuts:
            groups: dict[str, dict] = defaultdict(lambda: {"value": 0.0, "delta": 0.0, "n_sku": 0, "stores": set()})
            for s in skus:
                g = groups[group_key(s["segment"], s["size"], cut)]
                d = s["gp"][v] - s["gp"]["b_ewma"]
                g["value"] += d / abs(store_gp[s["store_id"]]) if store_gp[s["store_id"]] else 0.0
                g["delta"] += d
                g["n_sku"] += 1
                g["stores"].add(s["store_id"])
            use = sorted(k for k, g in groups.items() if g["value"] > 0)
            obj = sum(groups[k]["value"] for k in use)
            candidates.append({"variant": v, "size_cut": cut, "objective": round(obj, 5), "use_ml": use})
            if best is None or obj > best[0] + 1e-12:
                ev = {k: {"value": round(g["value"], 5), "delta_vnd": round(g["delta"]), "n_sku": g["n_sku"],
                          "n_stores": len(g["stores"]), "use_ml": k in use} for k, g in sorted(groups.items())}
                best = (obj, {"variant": v, "size_cut": cut, "use_ml": use, "objective": round(obj, 5),
                              "groups": ev})
    gate = best[1] if best else {"variant": "sym", "size_cut": None, "use_ml": [], "objective": 0.0, "groups": {}}
    gate["candidates"] = candidates
    gate["stores"] = sorted({s["store_id"] for s in skus})
    return gate


def fold_split(sizes: dict[int, int], seed: int = 0) -> dict[int, int]:
    """Chia diem ban thanh 2 nua co dinh, can theo quy mo: xep theo so mat hang, moi cap lien ke chia ngau nhien
    (co seed) mot diem cho moi nua."""
    import random

    rng = random.Random(seed)
    order = sorted(sizes, key=lambda s: (sizes[s], s))
    fold = {}
    for i in range(0, len(order), 2):
        pair = order[i:i + 2]
        flip = rng.random() < 0.5
        for j, sid in enumerate(pair):
            fold[sid] = (j + flip) % 2
    return fold


def crossfit_gates(skus: list[dict], store_gp: dict[int, float], fold: dict[int, int], **kw) -> dict[int, dict]:
    """Kiem cheo 2 lan: bo chon cho nua f chi hoc tu nua con lai. Tra ve {fold: gate}."""
    return {f: choose_gate([s for s in skus if fold[s["store_id"]] != f],
                           {k: v for k, v in store_gp.items() if fold.get(k) != f}, **kw) for f in (0, 1)}


def _gate_for_policy(gate: dict) -> dict:
    return {"variant": gate["variant"], "size_cut": gate["size_cut"], "use_ml": list(gate["use_ml"])}


def _kpis(k: dict) -> dict:
    return {x: k[x] for x in ("gross_profit", "waste_rate", "oos_rate", "oos_traffic")}


def _frn_learn_store(sid: int, t0: int) -> dict:
    """Pha 1 cua mot diem: A, B-EWMA va cac bien the B-ML; lai theo mat hang va nhom (segment luc T0)."""
    from app.ml.forecaster import load

    base, dates = frn_base(sid, t0)
    start, days = dates[t0 + 1], len(dates) - t0 - 1
    class_a = _class_a(base)
    ml = load("bt_")
    meta_gate = {"variant": "sym", "size_cut": None, "use_ml": sorted(ml.use_ml) if ml else []}
    all_sym = {"variant": "sym", "size_cut": None, "use_ml": "all"}
    policies = {
        "a": BaselineGoldenHourPolicy(),
        "b_ewma": OpsChestPolicy(ml_model=None),
        "b_ml": OpsChestPolicy(ml_model="bt_", gate=meta_gate),
        "b_ml_all": OpsChestPolicy(ml_model="bt_", gate=all_sym),
        "b_ml_split": OpsChestPolicy(ml_model="bt_", gate={**all_sym, "variant": "split"}),
        "b_ml_mid_ewma_sigma": OpsChestPolicy(ml_model="bt_", gate={**all_sym, "variant": "ewma_sigma"}),
    }
    runs = {k: _run(base, start, days, p, class_a) for k, p in policies.items()}
    probe = OpsChestPolicy()
    seg = {p.sku: (ml.segment(probe._demand(base, p, 120)) if ml else "?") for p in base.products}
    skus = [{"store_id": sid, "size": len(base.products), "sku": p.sku, "segment": seg[p.sku],
             "gp": {"b_ewma": runs["b_ewma"]["sku_gp"][p.sku], **{v: runs[r]["sku_gp"][p.sku] for v, r in ML_ALL.items()}}}
            for p in base.products]
    return {"store_id": sid, "products": len(base.products), "start": start.isoformat(), "days": days,
            "kpis": {k: _kpis(r) for k, r in runs.items()}, "skus": skus}


def _frn_gate_store(sid: int, t0: int, gate: dict, scen: list[str], a_kpis: dict) -> dict:
    """Pha 2 cua mot diem: chinh sach B-gate (bo chon hoc tren nua kia) va cac kich ban do nhay."""
    base, dates = frn_base(sid, t0)
    start, days = dates[t0 + 1], len(dates) - t0 - 1
    class_a = _class_a(base)
    g = _gate_for_policy(gate)
    b_gate = _kpis(_run(base, start, days, OpsChestPolicy(ml_model="bt_", gate=g), class_a))
    rows = {}
    for key in scen:
        _, _, make, react = FRN_SCENARIOS[key]
        world = base.world.scaled(react) if react != 1.0 else None
        if key == "reference":
            bk, ak = b_gate, a_kpis
        else:
            ak = _kpis(_run(base, start, days, BaselineGoldenHourPolicy(), class_a, world)) if world else a_kpis
            bk = _kpis(_run(base, start, days, make(g), class_a, world))
        rows[key] = {"gain": _pct(ak["gross_profit"], bk["gross_profit"]), "waste_a": ak["waste_rate"],
                     "waste_b": bk["waste_rate"], "oos_a": ak["oos_rate"], "oos_b": bk["oos_rate"]}
    return {"store_id": sid, "b_gate": b_gate, "scenarios": rows}


def _pmap(fn, arglist: list[tuple], workers: int, log, label: str) -> list:
    """Chay fn(*args) cho tung diem, song song theo tien trinh neu workers > 1; giu thu tu dau vao."""
    t = time.perf_counter()
    if workers <= 1:
        out = []
        for i, args in enumerate(arglist):
            out.append(fn(*args))
            log(f"[{label} {i + 1}/{len(arglist)}] điểm {args[0]} ({time.perf_counter() - t:.0f}s)")
        return out
    from concurrent.futures import ProcessPoolExecutor, as_completed

    res = [None] * len(arglist)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, *args): i for i, args in enumerate(arglist)}
        for n, f in enumerate(as_completed(futs)):
            i = futs[f]
            res[i] = f.result()
            log(f"[{label} {n + 1}/{len(arglist)}] điểm {arglist[i][0]} ({time.perf_counter() - t:.0f}s)")
    return res


def _app_gate_file(gate: dict, t0_date: str | None, n_stores: int, size_of_demo: int | None) -> dict:
    return {
        "version": 1,
        "variant": gate["variant"],
        "size_cut": gate["size_cut"],
        "use_ml": gate["use_ml"],
        "tiers": ({"nho": f"<= {gate['size_cut']} mặt hàng FRN", "lon": f"> {gate['size_cut']} mặt hàng FRN"}
                  if gate["size_cut"] is not None else None),
        "demo_store_size": size_of_demo,
        "selected_by": "Lãi trong backtest FRN (python -m app.sim.backtest --frn), không theo sai số dự báo",
        "data": f"{n_stores} điểm FRN giữ lại, so sánh từ ngày sau T0 = {t0_date}",
        "note": ("Bộ chọn học bằng mô hình backtest bt_q* (chỉ thấy dữ liệu đến T0) rồi áp cho mô hình chạy thật "
                 "q* (học thêm đến ngày 89). Học trên cả các điểm; kết quả ngoài mẫu của cách chọn này nằm trong "
                 "backtest.json (b_gate, kiểm chéo 2 lần theo điểm bán)."),
        "objective": gate["objective"],
        "groups": gate["groups"],
        "candidates": gate["candidates"],
    }


def run_frn(store_ids: list[int] | None = None, scenarios: list[str] | None = None, scenario_stores: int = 20,
            log=print, workers: int = 1, fold_seed: int = 0) -> dict:
    """So A (kinh nghiem + gio vang) voi cac bien the B tren tung diem FRN giu lai, cung nhu cau that:
      - b_ewma: OC voi engine EWMA; b_ml: bo chon cu (nhom trong meta.json, chon theo sai so du bao);
      - b_ml_all / b_ml_split: LightGBM o moi mat hang du lich su, sigma doi xung / phan phoi lech q10-q50-q90;
      - b_ml_mid_ewma_sigma: du bao diem LightGBM + do lech chuan EWMA (bien the "ewma_sigma");
      - b_gate: bo chon theo LAI, kiem cheo 2 lan theo diem ban - bo chon cua moi diem chi hoc tu nua con lai,
        nen ket qua b_gate la NGOAI MAU.
    Mo hinh backtest (bt_) chi thay du lieu den ngay T0. Cac kich ban do nhay chay B-gate tren `scenario_stores`
    diem dau tien. Ket qua co them `gate_app`: bo chon hoc tren tat ca cac diem (cho app, decision_gate.json)."""
    from app.sim import frn

    meta = frn.meta()
    t0 = int(meta.get("t0_day", 59))
    ids = store_ids or [int(s) for s in meta.get("heldout_stores", [])] or sorted(frn.stores())
    scen = scenarios if scenarios is not None else list(FRN_SCENARIOS)
    t_start = time.perf_counter()

    learned = _pmap(_frn_learn_store, [(sid, t0) for sid in ids], workers, log, "pha 1")
    sizes = {r["store_id"]: r["products"] for r in learned}
    skus = [s for r in learned for s in r["skus"]]
    store_gp = {r["store_id"]: r["kpis"]["b_ewma"]["gross_profit"] for r in learned}
    fold = fold_split(sizes, fold_seed)
    gates = crossfit_gates(skus, store_gp, fold)
    gate_app = choose_gate(skus, store_gp)
    for f, g in gates.items():
        log(f"Bộ chọn nửa {f} (học trên nửa {1 - f}): {g['variant']}, ngưỡng {g['size_cut']}, ML ở {g['use_ml']}")

    scen_ids = set(ids[:scenario_stores])
    tested = _pmap(_frn_gate_store, [(r["store_id"], t0, gates[fold[r["store_id"]]],
                                      scen if r["store_id"] in scen_ids else [], r["kpis"]["a"]) for r in learned],
                   workers, log, "pha 2")

    per_store, scen_rows = [], {k: [] for k in scen}
    for r, t in zip(learned, tested):
        k = {**r["kpis"], "b_gate": t["b_gate"]}
        a, ew = k["a"], k["b_ewma"]
        row = {"store_id": r["store_id"], "products": r["products"], "fold": fold[r["store_id"]],
               "start": r["start"], "days": r["days"], "gp_a": round(a["gross_profit"])}
        for v in B_VARIANTS:
            s = _short(v)
            row[f"gp_{v}"] = round(k[v]["gross_profit"])
            row[f"gain_{s}"] = _pct(a["gross_profit"], k[v]["gross_profit"])
            if v != "b_ewma":
                row[f"{s}_vs_ewma"] = _pct(ew["gross_profit"], k[v]["gross_profit"])
        for key in ("a", *B_VARIANTS):
            row[f"waste_{key}"] = k[key]["waste_rate"]
            row[f"oos_{key}"] = k[key]["oos_rate"]
            row[f"oos_traffic_{key}"] = k[key]["oos_traffic"]
        per_store.append(row)
        for key, x in t["scenarios"].items():
            scen_rows[key].append(x)

    def col(name, rows=per_store):
        return [r[name] for r in rows]

    def share(cond, rows=per_store):
        return round(sum(1 for r in rows if cond(r)) / len(rows), 4) if rows else 0.0

    names = []
    for v in B_VARIANTS:
        s = _short(v)
        names += [f"gain_{s}", f"waste_{v}", f"oos_{v}", f"oos_traffic_{v}"] + ([f"{s}_vs_ewma"] if v != "b_ewma" else [])
    summary = {n: _summary(col(n)) for n in ("waste_a", "oos_a", "oos_traffic_a", *names)}
    for v in B_VARIANTS:
        s = _short(v)
        summary[f"share_{s}_better_than_a"] = share(lambda r, s=s: r[f"gain_{s}"] > 0)
        if v != "b_ewma":
            summary[f"share_{s}_better_than_ewma"] = share(lambda r, s=s: r[f"{s}_vs_ewma"] > 0)
            summary[f"share_oos_{s}_not_worse"] = share(lambda r, v=v: r[f"oos_{v}"] <= r["oos_a"])
    # Theo quy mo diem ban (nguong cua bo chon cho app, mac dinh 30): ML thua ro o diem nho
    cut = gate_app["size_cut"] or 30
    summary["by_size"] = {"cut": cut, **{
        tier: {"stores": len(rows), **{f"{_short(v)}_vs_ewma": _summary(col(f"{_short(v)}_vs_ewma", rows)).get("median")
                                       for v in B_VARIANTS if v != "b_ewma"}}
        for tier, rows in (("nho", [r for r in per_store if r["products"] <= cut]),
                           ("lon", [r for r in per_store if r["products"] > cut]))}}
    scenarios_out = []
    for key in scen:
        rows = scen_rows[key]
        label, note, _, _ = FRN_SCENARIOS[key]
        scenarios_out.append({"key": key, "label": label, "note": note, "stores": len(rows),
                              **{f: _summary([r[f] for r in rows]).get("median") for f in
                                 ("gain", "waste_a", "waste_b", "oos_a", "oos_b")}})
    return {"source": "FreshRetailNet-50K", "t0_date": meta.get("t0_date"), "stores": len(per_store),
            "selection": "Bộ chọn theo lãi, chọn ngoài mẫu: kiểm chéo 2 lần theo điểm bán (b_gate)",
            "summary": summary, "per_store": per_store, "scenarios": scenarios_out,
            "gates": {f"fold{f}": {k: v for k, v in g.items() if k != "candidates"} for f, g in gates.items()},
            "gate_app": gate_app, "runtime_s": round(time.perf_counter() - t_start)}


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
    ap.add_argument("--frn", action="store_true", help=f"A/B trên các điểm FRN giữ lại, ghi vào {FRN_FILE.name}")
    ap.add_argument("--stores", type=int, default=None, help="--frn: chỉ chạy N điểm đầu")
    ap.add_argument("--scenario-stores", type=int, default=20, help="--frn: số điểm chạy các kịch bản độ nhạy")
    ap.add_argument("--out", type=Path, default=None, help="--frn: ghi kết quả vào file khác")
    ap.add_argument("--workers", type=int, default=None, help="--frn: số tiến trình chạy song song (mặc định: số lõi - 2)")
    ap.add_argument("--gate-out", type=Path, default=None,
                    help=f"--frn: nơi ghi bộ chọn cho app (mặc định ml/artifacts/decision_gate.json; '-' = không ghi)")
    args = ap.parse_args()
    if args.frn:
        from app.sim import frn
        ids = [int(s) for s in frn.meta().get("heldout_stores", [])] or sorted(frn.stores())
        import os

        from app.ml.forecaster import ARTIFACTS, GATE_FILE
        workers = args.workers if args.workers is not None else max(1, (os.cpu_count() or 2) - 2)
        out = run_frn(ids[:args.stores] if args.stores else ids, scenario_stores=args.scenario_stores, workers=workers)
        path = args.out or FRN_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        if str(args.gate_out) != "-":
            gpath = args.gate_out or ARTIFACTS / GATE_FILE
            gate = _app_gate_file(out["gate_app"], out["t0_date"], out["stores"], frn.store_size(frn.demo_store_id()))
            gpath.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Bộ chọn cho app -> {gpath}: {gate['variant']}, ngưỡng {gate['size_cut']}, ML ở {gate['use_ml']}")
        print(json.dumps(out["summary"], ensure_ascii=False, indent=1))
        for r in out["scenarios"]:
            print(f"{r['key']:<14} lãi {r['gain'] or 0:+.1%}  hủy {r['waste_a'] or 0:.1%}/{r['waste_b'] or 0:.1%}"
                  f"  hết hàng {r['oos_a'] or 0:.1%}/{r['oos_b'] or 0:.1%}  ({r['stores']} điểm)")
        return
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
