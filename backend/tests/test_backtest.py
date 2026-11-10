from datetime import date
from pathlib import Path

import pytest

from app.engines.disposition import ELASTICITY
from app.engines.forecast import baseline_demand
from app.sim import world as world_module
from app.sim.backtest import compare, run_backtest, warm_base
from app.sim.policies import BaselineGoldenHourPolicy, BaselinePolicy, OpsChestPolicy
from app.sim.world import OPTIMISTIC_WORLD, PESSIMISTIC_WORLD, REFERENCE_WORLD


def test_ops_chest_reduces_waste_without_hurting_profit_or_availability():
    # Tu khi co san muc phuc vu (N6), B doi bot phan giam huy de khong het hang nhieu hon A:
    # khong con ky vong giam huy >= 20% nhu truoc.
    res = run_backtest(date(2026, 8, 1), days=30, warmup=120)
    a, b = list(res["results"].values())
    assert b["waste_cost"] < a["waste_cost"]
    assert b["gross_profit"] > a["gross_profit"]
    assert b["oos_rate"] <= a["oos_rate"]
    assert b["oos_traffic"] <= a["oos_traffic"]


def test_service_floor_lowers_stockouts_vs_old_policy():
    base = warm_base(date(2026, 8, 1), warmup=120)
    new = compare(base, date(2026, 8, 1), 21)["results"]["B: Ops Chest"]
    old = compare(base, date(2026, 8, 1), 21, ops=OpsChestPolicy(service_floors=False))["results"]["B: Ops Chest"]
    assert new["oos_rate"] < old["oos_rate"] and new["oos_class_a"] < old["oos_class_a"]


def test_default_baseline_also_marks_down():
    res = run_backtest(date(2026, 8, 1), days=14, warmup=60, ops=OpsChestPolicy(dispose=False))
    a = res["results"][BaselineGoldenHourPolicy.name]
    assert a["markdown_loss"] > 0


def test_world_does_not_share_constants_with_engine():
    source = Path(world_module.__file__).read_text(encoding="utf-8")
    assert not any(line.startswith(("from app.engines", "import app.engines")) for line in source.splitlines())
    assert REFERENCE_WORLD.elasticity != ELASTICITY


def test_world_elasticity_changes_outcome_but_not_policy():
    base = warm_base(date(2026, 8, 1), warmup=60)
    high = compare(base, date(2026, 8, 1), 14, world=OPTIMISTIC_WORLD)
    low = compare(base, date(2026, 8, 1), 14, world=PESSIMISTIC_WORLD)
    assert high["results"]["B: Ops Chest"]["revenue"] != low["results"]["B: Ops Chest"]["revenue"]


def test_non_fefo_customers_increase_waste():
    base = warm_base(date(2026, 8, 1), warmup=60)
    fefo = compare(base, date(2026, 8, 1), 21, baseline=BaselinePolicy())
    mixed = compare(base, date(2026, 8, 1), 21, world=REFERENCE_WORLD.with_fefo(0.5), baseline=BaselinePolicy())
    name = BaselinePolicy.name
    assert mixed["results"][name]["waste_cost"] > fefo["results"][name]["waste_cost"]


def test_partial_approval_changes_outcome():
    base = warm_base(date(2026, 8, 1), warmup=60)
    full = compare(base, date(2026, 8, 1), 14)["results"]["B: Ops Chest"]
    partial = compare(base, date(2026, 8, 1), 14, ops=OpsChestPolicy(approval_rate=0.5))["results"]["B: Ops Chest"]
    assert partial["gross_profit"] != full["gross_profit"]


def test_baseline_demand_drops_evening_clearance():
    assert baseline_demand(10, 0, 0.0, 4, 3.0) == 6


def test_baseline_demand_deflates_all_day_discount():
    # giam 50%, co gian 2 -> nhu cau gap doi: 10 don vi ban giam gia tuong duong 5 don vi gia goc
    assert baseline_demand(10, 10, 0.5, 0, 2.0) == pytest.approx(5)


def test_baseline_demand_keeps_full_price_days():
    assert baseline_demand(7, 0, 0.0, 0, 3.0) == 7
