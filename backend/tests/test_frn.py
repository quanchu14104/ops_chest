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

        def eligible(self, history, store_size=None, gate=None):
            return self.ok

        def asymmetric(self, gate=None):
            return False

        def sigma_mode(self, gate=None):
            return "sym"

        def forecast(self, history, stockout, end, horizon, statics, start=None, holiday_of=None, asymmetric=None):
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


def test_real_model_loads_from_crlf_files(tmp_path):
    """Checkout tren Windows (core.autocrlf) doi file mo hinh sang CRLF; LightGBM doc truc tiep thi sap ca tien trinh."""
    from app.ml.forecaster import ARTIFACTS, MlForecaster
    _real_model()
    (tmp_path / "meta.json").write_bytes((ARTIFACTS / "meta.json").read_bytes())
    for q in (10, 50, 90):
        raw = (ARTIFACTS / f"bt_q{q}.txt").read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / f"bt_q{q}.txt").write_bytes(raw.replace(b"\n", b"\r\n"))
    m = MlForecaster(tmp_path, "bt_")
    fc = m.forecast([8.0] * 60, [False] * 60, date(2024, 5, 31), 14, (1, 10, 100))
    assert fc.method == "lightgbm_frn" and all(x >= 0 for x in fc.daily)


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


def test_real_model_split_normal_matches_quantiles():
    """sigma_lo / sigma_hi khop q10 / q90 quanh q50: q10 = mid - Z90*sigma_lo, q90 = mid + Z90*sigma_hi (TB 7 ngay)."""
    from app.ml.forecaster import Z90
    m = _real_model()
    rng = np.random.default_rng(5)
    hist = list(rng.poisson(12, 60).astype(float))
    end = date(2024, 5, 31)
    m._cache.clear()
    fc = m.forecast(hist, [False] * 60, end, 14, (1, 10, 100), asymmetric=True)
    lo, mid, hi, _ = next(iter(m._cache.values()))
    lo, mid, hi = lo[0], mid[0], hi[0]
    assert fc.sigma_lo == pytest.approx(max(float(np.mean(mid - lo)) / Z90, 0.1))
    assert fc.sigma_hi == pytest.approx(max(float(np.mean(hi - mid)) / Z90, 0.1))
    assert fc.sigma_daily == pytest.approx(max(float(np.mean(hi - lo)) / (2 * Z90), 0.1))  # giu nguyen sigma cu
    sym = m.forecast(hist, [False] * 60, end, 14, (1, 10, 100), asymmetric=False)
    assert sym.sigma_lo is None and sym.sigma_hi is None and sym.daily == fc.daily


# ---------------------------------------------------------------- bo chon theo lai (decision_gate.json)
def _stub_forecaster(art_dir, use_ml=("ban_vua|deu",)):
    """MlForecaster khong nap LightGBM: chi phan nhom va bo chon (doc decision_gate.json trong art_dir)."""
    from app.ml.forecaster import MlForecaster, load_gate

    class Stub(MlForecaster):
        def __init__(self):
            self.cuts, self.zero_cut, self.use_ml = (5.0, 9.0), 0.3, set(use_ml)
            self.gate = load_gate(art_dir)

        def forecast(self, history, stockout, end, horizon, statics, start=None, holiday_of=None, asymmetric=None):
            return Forecast(start=end + timedelta(days=1), daily=[1.0] * horizon, sigma_daily=1.0, level=1.0,
                            weekday_index=[1.0] * 7, method="lightgbm_frn",
                            sigma_lo=0.5 if asymmetric else None, sigma_hi=2.0 if asymmetric else None)
    return Stub()


def test_gate_file_overrides_meta_segments(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr("app.config.settings.forecast_engine", "auto")
    mid = [7.0] * 60  # ban_vua|deu
    m = _stub_forecaster(tmp_path)
    assert m.gate is None and m.eligible(mid)  # thieu file: theo meta (ban_vua|deu duoc dung ML)
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: m)
    fc = forecast_router.forecast(mid, END, 7, frn_statics=(1, 2, 3), store_size=164)
    assert fc.method == "lightgbm_frn" and fc.sigma_hi is None  # meta: doi xung nhu cu

    (tmp_path / "decision_gate.json").write_text(json.dumps(
        {"variant": "split", "size_cut": 30, "use_ml": ["ban_vua|deu|lon"]}), encoding="utf-8")
    m = _stub_forecaster(tmp_path)
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: m)
    big = forecast_router.forecast(mid, END, 7, frn_statics=(1, 2, 3), store_size=164)  # cua hang demo: 164 mat hang
    assert big.method == "lightgbm_frn" and (big.sigma_lo, big.sigma_hi) == (0.5, 2.0)  # bien the split
    small = forecast_router.forecast(mid, END, 7, frn_statics=(1, 2, 3), store_size=20)  # diem nho: nhom bi loai
    assert small.method.startswith("ewma")
    assert forecast_router.forecast(mid, END, 7, frn_statics=(1, 2, 3)).method.startswith("ewma")  # khong ro quy mo
    assert forecast_router.forecast([1.0] * 60, END, 7, frn_statics=(1, 2, 3), store_size=164).method.startswith("ewma")
    # bo chon tam cua backtest thay cho file
    assert forecast_router.forecast(mid, END, 7, frn_statics=(1, 2, 3), store_size=20,
                                    gate={"variant": "sym", "size_cut": None, "use_ml": "all"}).method == "lightgbm_frn"


def test_broken_gate_file_falls_back_to_meta(tmp_path):
    (tmp_path / "decision_gate.json").write_text("{khong phai json", encoding="utf-8")
    m = _stub_forecaster(tmp_path)
    assert m.gate is None and m.eligible([7.0] * 60)


def test_demo_store_size_is_its_frn_sku_count():
    if not frn.available():
        pytest.skip("Chưa có dữ liệu FRN")
    frn._all.cache_clear()
    from app.ml.forecaster import store_tier
    assert frn.store_size(frn.demo_store_id()) == len(frn.store().series) == 164
    assert store_tier(164, 30) == "lon" and store_tier(30, 30) == "nho"


def _sku_rows():
    """4 diem, 2 nhom. ML thang o diem lon (+), thua o diem nho (-)."""
    rows = []
    for sid, size, d in ((1, 20, -50.0), (2, 25, -40.0), (3, 120, 30.0), (4, 150, 20.0)):
        for seg in ("ban_vua|deu", "ban_it|deu"):
            rows.append({"store_id": sid, "size": size, "sku": f"{sid}{seg}", "segment": seg,
                         "gp": {"b_ewma": 100.0, "sym": 100.0 + d, "split": 100.0 + d / 2, "ewma_sigma": 100.0 + d / 4}})
    return rows, {1: 1000.0, 2: 1000.0, 3: 1000.0, 4: 1000.0}


def test_choose_gate_picks_profitable_groups_by_size():
    from app.sim.backtest import choose_gate
    rows, gp = _sku_rows()
    g = choose_gate(rows, gp, cuts=(None, 50))
    assert g["size_cut"] == 50 and g["variant"] == "sym"
    assert g["use_ml"] == ["ban_it|deu|lon", "ban_vua|deu|lon"]
    assert choose_gate(rows, gp, cuts=(None,))["use_ml"] == []  # khong chia quy mo: tong ML thua -> EWMA moi noi


def test_crossfit_never_uses_test_stores():
    from app.sim.backtest import crossfit_gates, fold_split
    rows, gp = _sku_rows()
    fold = fold_split({1: 20, 2: 25, 3: 120, 4: 150}, seed=0)
    assert sorted(fold.values()) == [0, 0, 1, 1]
    assert fold[1] != fold[2] and fold[3] != fold[4]  # can theo quy mo: moi nua co 1 diem nho, 1 diem lon
    gates = crossfit_gates(rows, gp, fold, cuts=(None, 50))
    for f in (0, 1):
        assert set(gates[f]["stores"]) == {s for s, k in fold.items() if k != f}
        # Doi lai cua cac diem "thi" (nua f) thanh cuc doan: bo chon cua nua f khong doi
        poisoned = [dict(r, gp={k: (1e9 if k != "b_ewma" else 0.0) for k in r["gp"]}) if fold[r["store_id"]] == f
                    else r for r in rows]
        again = crossfit_gates(poisoned, gp, fold, cuts=(None, 50))
        assert again[f]["use_ml"] == gates[f]["use_ml"] and again[f]["variant"] == gates[f]["variant"]


def test_gate_ewma_sigma_variant_keeps_ml_point_forecast_with_ewma_sigma(tmp_path, monkeypatch):
    """Bien the "ewma_sigma": du bao diem cua LightGBM, do lech chuan cua EWMA cho cung chuoi."""
    import json
    from app.engines.forecast import forecast_demand
    monkeypatch.setattr("app.config.settings.forecast_engine", "auto")
    (tmp_path / "decision_gate.json").write_text(json.dumps(
        {"variant": "ewma_sigma", "size_cut": 30, "use_ml": ["ban_vua|deu|lon"]}), encoding="utf-8")
    m = _stub_forecaster(tmp_path)
    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: m)
    hist = [7.0, 9.0, 6.0, 8.0, 7.0, 5.0, 10.0] * 9
    fc = forecast_router.forecast(hist, END, 7, frn_statics=(1, 2, 3), store_size=164)
    ewma = forecast_demand(hist, END, 7)
    assert fc.method == "lightgbm_frn" and fc.daily == [1.0] * 7  # du bao diem tu LightGBM (stub)
    assert fc.sigma_daily == pytest.approx(ewma.sigma_daily) and fc.sigma_daily != 1.0
    assert fc.sigma_lo is None and fc.sigma_hi is None
    # Bo chon tam "sym" thi giu sigma cua LightGBM
    sym = forecast_router.forecast(hist, END, 7, frn_statics=(1, 2, 3), store_size=164,
                                   gate={"variant": "sym", "size_cut": None, "use_ml": "all"})
    assert sym.sigma_daily == 1.0
