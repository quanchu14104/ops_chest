from datetime import date

from app.sim.backtest import run_backtest


def test_ops_chest_reduces_waste_without_hurting_profit():
    res = run_backtest(date(2026, 8, 1), days=30, warmup=120)
    a, b = list(res["results"].values())
    assert b["waste_cost"] < a["waste_cost"] * 0.8
    assert b["gross_profit"] > a["gross_profit"]
