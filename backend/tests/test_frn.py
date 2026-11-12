"""FreshRetailNet-50K trong OC: doc du lieu, danh muc, nguon nhu cau, bo chon du bao, dac trung dung chung.

Du lieu trong test la file FRN NHO tu tao (cung dinh dang stores_daily.csv.gz), khong can file that, khong ghi DB.
"""
import csv
import gzip
from datetime import date, timedelta

import numpy as np
import pytest

from app.engines import forecast_router
from app.engines.forecast import Forecast
from app.engines.ml_features import FEATURES, MAX_H, build_features, impute_stockouts
from app.engines.replenishment import LotState, ReplenishmentInput, compute_order
from app.sim import frn
from app.sim.demand import FrnDemand, FrnRangeError
from app.sim.frn_catalog import build_frn_catalog
from app.sim.policies import BaselinePolicy
from app.sim.store_sim import StoreSim

START = date(2024, 3, 28)
DAYS = 97
COLS = ["store_id", "product_id", "city_id", "management_group_id", "first_category_id", "second_category_id",
        "third_category_id", "day", "dt", "sale", "demand", "stock_hours", "discount", "activity", "holiday"]


@pytest.fixture()
def frn_file(tmp_path):
    rng = np.random.default_rng(0)
    path = tmp_path / "stores_daily.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for store in (18, 99):
            for pid, (g, c1, c2, rate) in {101: (1, 10, 100, 1.2), 102: (1, 10, 100, 0.4), 203: (2, 20, 200, 2.0)}.items():
                for day in range(DAYS):
                    d = START + timedelta(days=day)
                    sale = float(rng.poisson(rate * 10)) / 10
                    w.writerow([store, pid, 1, g, c1, c2, 1000 + pid, day, d.isoformat(), sale, sale * 1.1,
                                3 if day % 9 == 0 else 0, 1.0, 0, int(d.weekday() >= 5)])
    frn._all.cache_clear()
    yield path
    frn._all.cache_clear()


def test_load_store(frn_file):
    st = frn.store(18, frn_file)
    assert st.dates[0] == START and len(st.dates) == DAYS
    assert set(st.series) == {101, 102, 203}
    s = st.series[203]
    assert (s.management_group_id, s.first_category_id, s.second_category_id) == (2, 20, 200)
    assert len(s.demand) == DAYS and s.stock_hours[0] == 3
    hol = frn.holiday_of(st)
    assert hol(date(2024, 3, 30)) == 1 and hol(date(2024, 4, 1)) == 0
    assert hol(date(2024, 12, 7)) == 1  # ngoai khoang du lieu: cuoi tuan


def test_catalog_and_demand(frn_file):
    st = frn.store(18, frn_file)
    suppliers, products = build_frn_catalog(st, k=10)
    assert len(suppliers) == 2  # moi nhom quan ly mot NCC
    assert {p.sku for p in products} == {"F0101", "F0102", "F0203"}
    for p in products:
        assert p.freshness_class == "FRESH" and 1 <= p.shelf_life_days <= 3
        assert 0 < p.unit_cost < p.unit_price
        assert p.frn_id is not None
    assert all(p.is_traffic_driver for p in products)  # chi 3 mat hang -> deu nam trong top 5
    dem = FrnDemand(st, 10)
    p = next(x for x in products if x.frn_id == 203)
    assert dem.need(p, START) == int(round(st.series[203].demand[0] * 10))
    assert dem.expected(p, START) == pytest.approx(st.series[203].demand[0] * 10)
    with pytest.raises(FrnRangeError):
        dem.need(p, START + timedelta(days=DAYS))


def test_store_sim_runs_on_frn_demand(frn_file):
    st = frn.store(18, frn_file)
    suppliers, products = build_frn_catalog(st, k=10)
    sim = StoreSim(suppliers, products, demand=FrnDemand(st, 10))
    for p in products:
        sim.add_lot(p.sku, 30, START - timedelta(days=1), p.unit_cost)
    sim.run(START, 30, BaselinePolicy())
    for p in products:
        h = sim.hist[p.sku]
        need = [FrnDemand(st, 10).need(p, START + timedelta(days=i)) for i in range(30)]
        assert all(s + lost == n for s, lost, n in zip(h["sales"], h["lost"], need))


# ---------------------------------------------------------------- dac trung dung chung (Kaggle va OC)
def _panel(n=4, T=40, seed=1):
    rng = np.random.default_rng(seed)
    Y = rng.poisson(5, (n, T)).astype(float)
    S = np.zeros((n, T), bool)
    wd = np.arange(T + MAX_H) % 7
    return Y, S, wd, np.zeros(T + MAX_H)


END = date(2024, 5, 31)


def test_features_shape_and_scale_free():
    Y, S, wd, hol = _panel()
    # Cung mot cua hang: Y o don vi FRN (K=10) va Y*10 o don vi cua hang -> EWMA giong nhau, moi dac trung giong nhau
    X, level = build_features(Y, S, 39, range(1, MAX_H + 1), wd, hol, end=END, unit_k=10)
    assert X.shape == (4 * MAX_H, len(FEATURES))
    X10, level10 = build_features(Y * 10, S, 39, range(1, MAX_H + 1), wd, hol, end=END, unit_k=1)
    assert np.allclose(level10, level * 10)
    keep = [i for i, f in enumerate(FEATURES) if f != "log_level"]
    assert np.allclose(X[:, keep], X10[:, keep], atol=1e-4)  # chia cho muc nen: chi log_level phu thuoc don vi


def test_features_include_ewma_forecast():
    from app.engines.forecast import forecast_demand
    Y, S, wd, hol = _panel(n=1)
    X, level = build_features(Y, S, 39, [1], wd, hol, end=END, unit_k=1)
    fc = forecast_demand(Y[0, :40].tolist(), END, MAX_H, stockout=[False] * 40, event_factors={})
    assert X[0, FEATURES.index("ewma_h")] == pytest.approx(fc.daily[0] / level[0], rel=1e-4)


def test_features_need_28_days():
    Y, S, wd, hol = _panel(T=40)
    with pytest.raises(ValueError):
        build_features(Y, S, 20, range(1, 8), wd, hol, end=END)


def test_stockout_days_imputed_upward_only():
    Y = np.array([[10.0, 2.0, 10.0, 12.0, 3.0, 11.0, 9.0]])
    S = np.array([[False, True, False, False, True, False, False]])
    wd = np.zeros(7, int)  # cung mot thu
    out = impute_stockouts(Y, S, wd)
    mean_ok = np.mean([10, 10, 12, 11, 9])
    assert out[0, 1] == pytest.approx(mean_ok) and out[0, 4] == pytest.approx(mean_ok)
    assert out[0, 0] == 10.0  # ngay con hang giu nguyen
    Y2 = np.array([[10.0, 30.0, 10.0]])
    assert impute_stockouts(Y2, np.array([[False, True, False]]), np.zeros(3, int))[0, 1] == 30.0  # khong keo xuong


# ---------------------------------------------------------------- bo chon du bao
def test_router_uses_ewma_without_frn(monkeypatch):
    monkeypatch.setattr("app.config.settings.forecast_engine", "auto")
    hist = [5.0] * 60
    fc = forecast_router.forecast(hist, date(2024, 5, 31), 7)
    assert fc.method.startswith("ewma")


def test_router_falls_back_when_model_missing(monkeypatch):
    monkeypatch.setattr("app.config.settings.forecast_engine", "auto")
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: None)
    fc = forecast_router.forecast([5.0] * 60, date(2024, 5, 31), 7, frn_statics=(1, 10, 100))
    assert fc.method.startswith("ewma")


def test_router_respects_config_and_eligibility(monkeypatch):
    calls = []

    class Fake:
        def __init__(self, ok):
            self.ok = ok

        def eligible(self, history):
            return self.ok

        def forecast(self, history, stockout, end, horizon, statics, start=None, holiday_of=None):
            calls.append(statics)
            return Forecast(start=end + timedelta(days=1), daily=[1.0] * horizon, sigma_daily=1.0, level=1.0,
                            weekday_index=[1.0] * 7, method="lightgbm_frn")

    monkeypatch.setattr("app.config.settings.forecast_engine", "auto")
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: Fake(True))
    assert forecast_router.forecast([5.0] * 60, date(2024, 5, 31), 7, frn_statics=(1, 2, 3)).method == "lightgbm_frn"
    assert calls == [(1, 2, 3)]
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: Fake(False))  # nhom ML thua EWMA
    assert forecast_router.forecast([5.0] * 60, date(2024, 5, 31), 7, frn_statics=(1, 2, 3)).method.startswith("ewma")
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: Fake(True))
    monkeypatch.setattr("app.config.settings.forecast_engine", "ewma")
    assert forecast_router.forecast([5.0] * 60, date(2024, 5, 31), 7, frn_statics=(1, 2, 3)).method.startswith("ewma")


# ---------------------------------------------------------------- mo hinh that (bo qua neu chua co file)
def _real_model():
    from app.ml.forecaster import load
    load.cache_clear()
    m = load("")
    if m is None:
        pytest.skip("Chưa có mô hình LightGBM trong app/ml/artifacts")
    return m


def test_real_model_returns_forecast():
    m = _real_model()
    rng = np.random.default_rng(3)
    hist = list(rng.poisson(8, 60).astype(float))
    so = [False] * 60
    end = date(2024, 5, 31)
    fc = m.forecast(hist, so, end, 14, (1, 10, 100))
    assert fc.method == "lightgbm_frn" and len(fc.daily) == 14 and fc.start == end + timedelta(days=1)
    assert all(x >= 0 for x in fc.daily) and fc.sigma_daily > 0
    assert 2 < sum(fc.daily[:7]) / 7 < 30  # cung bac voi muc ban 8/ngay
    assert fc.daily[7:14] == pytest.approx([fc.daily[i] for i in range(7)])  # tuan 2 lap lai theo thu


def test_real_model_forecast_still_capped_by_capacity_and_shelf_life():
    m = _real_model()
    end = date(2024, 5, 31)
    fc = m.forecast([20.0] * 60, [False] * 60, end, 14, (1, 10, 100))
    base = dict(today=end, lead_time_days=1, review_period_days=1, shelf_life_days=2, forecast=fc,
                lots=[LotState(qty=0, expiry=end)], unit_cost=7000, unit_price=10000, min_service_level=0.95)
    capped = compute_order(ReplenishmentInput(**base, max_stock=5))
    assert capped.qty <= 5 and capped.capped_by_capacity
    free = compute_order(ReplenishmentInput(**base))
    assert free.qty <= free.shelf_life_cap + 1  # tran HSD 2 ngay van chan khi du bao do LightGBM tinh
