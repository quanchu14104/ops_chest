from datetime import date, timedelta

import pytest

from app.engines.abc_xyz import SkuStats, classify, delist_candidates
from app.engines.disposition import DispositionInput, evaluate
from app.engines.expiry import LotInput, project_lots
from app.engines.forecast import Forecast, forecast_demand
from app.engines.replenishment import (LotState, ReplenishmentInput, compute_order, newsvendor_service_level,
                                       review_period)

T = date(2026, 11, 4)  # Thu 4


def flat(level: float, sigma: float = 1.0, start: date = T + timedelta(days=1), n: int = 60) -> Forecast:
    return Forecast(start=start, daily=[level] * n, sigma_daily=sigma, level=level, weekday_index=[1.0] * 7)


def inp(**kw) -> ReplenishmentInput:
    base = dict(today=T, lead_time_days=1, review_period_days=1, shelf_life_days=365, forecast=flat(10),
                lots=[], pack_size=1, z=1.65, unit_cost=60, unit_price=100)
    base.update(kw)
    return ReplenishmentInput(**base)


# ---------------- replenishment ----------------
def test_shelf_life_cap_limits_order_for_perishables():
    # Chu ky phu 3 ngay (30 don vi) nhung hang chi song 1 ngay -> chi ban kip ~10
    r = compute_order(inp(review_period_days=3, shelf_life_days=1, forecast=flat(10, sigma=2)))
    assert r.capped_by_shelf_life
    assert r.qty <= 10 + 3  # ~ nhu cau 1 ngay + ton an toan nho
    long = compute_order(inp(review_period_days=3, shelf_life_days=365, forecast=flat(10, sigma=2)))
    assert long.qty >= 30


def test_lots_expiring_before_arrival_are_not_counted():
    lead = 3
    no_stock = compute_order(inp(lead_time_days=lead, review_period_days=7, shelf_life_days=60, forecast=flat(5)))
    # 100 don vi nhung het han ngay mai: khong the phuc vu chu ky sau khi hang ve
    expiring = compute_order(inp(lead_time_days=lead, review_period_days=7, shelf_life_days=60, forecast=flat(5),
                                 lots=[LotState(100, T + timedelta(days=1))]))
    fresh = compute_order(inp(lead_time_days=lead, review_period_days=7, shelf_life_days=60, forecast=flat(5),
                              lots=[LotState(100, T + timedelta(days=50))]))
    assert expiring.qty == no_stock.qty
    assert expiring.expected_waste_before_arrival > 80
    assert fresh.qty == 0


def test_pack_size_rounding_up_for_long_life():
    r = compute_order(inp(pack_size=24, forecast=flat(3), review_period_days=4))
    assert r.qty % 24 == 0 and r.qty > 0


def test_newsvendor_service_level_moves_with_salvage_and_penalty():
    base = newsvendor_service_level(60, 100, 0)
    assert newsvendor_service_level(60, 100, 40) > base  # thu hoi tot -> dam dat nhieu hon
    assert newsvendor_service_level(60, 100, 0, stockout_penalty=100) > base  # hang keo khach


def test_review_period():
    assert review_period([0, 3], date(2026, 11, 2)) == 3  # T2 -> T5
    assert review_period([0, 3], date(2026, 11, 5)) == 4  # T5 -> T2


# ---------------- forecast ----------------
def test_censored_days_raise_forecast_above_naive_mean():
    end = date(2026, 11, 1)
    sales, so = [], []
    for i in range(56):
        if i % 2 == 0:
            sales.append(6), so.append(True)  # het hang o muc 6 (nhu cau that ~10)
        else:
            sales.append(9), so.append(False)
    naive = sum(sales) / len(sales)
    fc = forecast_demand(sales, end, 7, stockout=so)
    assert fc.level > naive
    assert fc.n_censored == 28


def test_weekday_pattern_learned():
    end = date(2026, 11, 1)  # CN
    sales = [20 if (end - timedelta(days=55 - i)).weekday() < 5 else 5 for i in range(56)]
    fc = forecast_demand(sales, end, 7)
    weekday_avg = sum(fc.daily[:5]) / 5  # T2-T6
    weekend_avg = sum(fc.daily[5:]) / 2
    assert weekday_avg > 2.5 * weekend_avg


# ---------------- expiry ----------------
def test_project_lots_fefo():
    lots = [LotInput(1, 10, T + timedelta(days=1)), LotInput(2, 10, T + timedelta(days=5))]
    r = {x.lot_id: x for x in project_lots(lots, [3.0] * 10, T)}
    assert r[1].expected_sold == 6 and r[1].expected_waste == 4  # ban 3/ngay trong 2 ngay
    assert r[2].expected_waste == 0


# ---------------- disposition ----------------
def test_return_wins_when_credit_high_and_allowed():
    opts = evaluate(DispositionInput(qty=20, unit_cost=10000, unit_price=14000, days_left=10,
                                     expected_sold_full_price=5, elasticity=1.2, accepts_return=True,
                                     return_min_days_before_expiry=7, return_credit_pct=0.9))
    assert opts[0].action == "RETURN"


def test_return_infeasible_outside_window():
    opts = evaluate(DispositionInput(qty=20, unit_cost=10000, unit_price=14000, days_left=3,
                                     expected_sold_full_price=5, elasticity=1.2, accepts_return=True,
                                     return_min_days_before_expiry=7, return_credit_pct=0.9))
    ret = next(o for o in opts if o.action == "RETURN")
    assert not ret.feasible and opts[0].action != "RETURN"


def test_last_day_uses_evening_markdown_on_leftover_only():
    opts = evaluate(DispositionInput(qty=10, unit_cost=25000, unit_price=40000, days_left=0,
                                     expected_sold_full_price=6, elasticity=3.0, daily_demand=6))
    assert opts[0].action == "MARKDOWN" and opts[0].timing == "EVENING"
    assert opts[0].delta_vs_keep > 0


def test_keep_when_no_waste_expected():
    opts = evaluate(DispositionInput(qty=5, unit_cost=1, unit_price=2, days_left=4,
                                     expected_sold_full_price=5, elasticity=2.0))
    assert opts[0].action == "KEEP"


# ---------------- ABC-XYZ ----------------
def test_abc_xyz_thresholds_and_delist_rules():
    stats = [
        SkuStats("A1", "Hang chu luc", 800, [10] * 13),
        SkuStats("B1", "Hang vua", 150, [5, 6, 4, 5, 7, 3, 5, 6, 4, 5, 6, 4, 5]),
        SkuStats("C1", "Hang lo", -20, [0, 0, 5, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0], waste_rate=0.4, substitutes=["X"]),
        SkuStats("C2", "Nuoc suoi", 30, [0, 0, 6, 0, 0, 0, 3, 0, 0, 0, 0, 4, 0], waste_rate=0.4,
                 is_traffic_driver=True),
    ]
    cls = classify(stats)
    assert cls["A1"].cell == "AX"
    assert cls["B1"].abc == "B"
    assert cls["C1"].cell == "CZ"
    cands = delist_candidates(stats, cls)
    assert [c["sku"] for c in cands] == ["C1"]  # hang keo khach khong bao gio bi de xuat ngung nhap


# ---------------- phan phoi lech (sigma_lo / sigma_hi cua mo hinh phan vi) ----------------
def _skew(level: float, lo: float | None, hi: float | None, sigma: float = 2.0) -> Forecast:
    fc = flat(level, sigma=sigma)
    fc.sigma_lo, fc.sigma_hi = lo, hi
    return fc


def test_symmetric_forecast_orders_exactly_as_before():
    """sigma_lo/hi = None: ket qua y het cong thuc cu (z * sigma_daily), ca hang tuoi lan hang ben."""
    import math
    from statistics import NormalDist
    for kw in (dict(shelf_life_days=2, review_period_days=1, unit_cost=30, unit_price=100),   # newsvendor, z > 0
               dict(shelf_life_days=2, review_period_days=1, unit_cost=95, unit_price=100),   # newsvendor, z < 0
               dict(shelf_life_days=365, review_period_days=3)):                                # order-up-to
        old = compute_order(inp(forecast=flat(10, sigma=3), **kw))
        same = compute_order(inp(forecast=_skew(10, 3.0, 3.0, sigma=3), **kw))
        assert old.to_dict() == same.to_dict()
        L, R = 1, kw["review_period_days"]
        horizon = R if kw["shelf_life_days"] <= R + 7 else L + R
        assert old.safety_stock == pytest.approx(NormalDist().inv_cdf(old.service_level) * 3 * math.sqrt(horizon))


def test_skewed_sigma_uses_upper_side_when_z_positive():
    kw = dict(shelf_life_days=2, review_period_days=1, unit_cost=30, unit_price=100)  # muc phuc vu 70%
    r = compute_order(inp(forecast=_skew(10, lo=0.5, hi=4.0), **kw))
    ref = compute_order(inp(forecast=flat(10, sigma=4.0), **kw))  # doi xung voi sigma = phia tren
    assert r.service_level > 0.5
    assert r.safety_stock == pytest.approx(ref.safety_stock) and r.qty == ref.qty
    assert r.shelf_life_cap == pytest.approx(ref.shelf_life_cap)  # tran HSD (z >= 0) cung dung phia tren


def test_skewed_sigma_uses_lower_side_when_z_negative():
    kw = dict(shelf_life_days=2, review_period_days=1, unit_cost=95, unit_price=100, salvage_per_unit=0)
    r = compute_order(inp(forecast=_skew(10, lo=0.5, hi=4.0), **kw))
    ref = compute_order(inp(forecast=flat(10, sigma=0.5), **kw))
    assert r.service_level < 0.5
    assert r.safety_stock == pytest.approx(ref.safety_stock) and r.safety_stock < 0
    # tran HSD dung z_cap = 0 nen khong phu thuoc sigma
    assert r.shelf_life_cap == pytest.approx(ref.shelf_life_cap)
