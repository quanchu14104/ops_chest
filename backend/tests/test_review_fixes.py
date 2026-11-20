"""Hoi quy cho cac loi tim thay khi review logic toan du an (11/2026): phan khong can DB."""
from datetime import date, timedelta

import pytest

from app.agent.guard import check_answer
from app.engines import forecast_router
from app.engines.disposition import DispositionInput, evaluate
from app.engines.expiry import BUCKET_ORDER, OVERDUE, bucket
from app.engines.forecast import Forecast
from app.engines.replenishment import forecast_horizon

END = date(2024, 5, 31)


def _fc(daily, start=END + timedelta(days=1), method="lightgbm_frn"):
    return Forecast(start=start, daily=list(daily), sigma_daily=1.0, level=1.0, weekday_index=[1.0] * 7, method=method)


# ---- LightGBM khong duoc thay ngay su kien SM da khai bao (gia thuyet)
def test_event_days_are_replaced_by_normal_same_weekday_level():
    hist = [10.0] * 53 + [30.0] * 3
    skip = {END - timedelta(days=i) for i in range(3)}
    y, s = forecast_router.mask_event_days(hist, [False] * 56, END, skip)
    assert y[-3:] == [10.0] * 3 and y[:-3] == hist[:-3] and not any(s)
    same, _ = forecast_router.mask_event_days(hist, [False] * 56, END, None)
    assert same is hist  # khong co su kien: giu nguyen


def test_router_feeds_masked_history_to_lightgbm(monkeypatch):
    monkeypatch.setattr("app.config.settings.forecast_engine", "auto")
    seen = {}

    class Stub:
        def eligible(self, history, store_size=None, gate=None):
            return True

        def asymmetric(self, gate=None):
            return False

        def sigma_mode(self, gate=None):
            return "sym"

        def forecast(self, history, stockout, end, horizon, statics, **kw):
            seen["history"] = list(history)
            return _fc([1.0] * horizon)

    monkeypatch.setattr("app.ml.forecaster.load", lambda prefix="", art_dir=None: Stub())
    hist = [10.0] * 57 + [30.0] * 3
    skip = {END - timedelta(days=i) for i in range(3)}
    forecast_router.forecast(hist, END, 7, frn_statics=(1, 2, 3), skip_dates=skip)
    assert seen["history"][-3:] == [10.0] * 3


def test_lightgbm_ewma_feature_sees_the_training_lookback(monkeypatch):
    """Luc huan luyen, dac trung ewma_h/ewma_sigma chay EWMA tren 56 ngay; luc chay khong duoc cat con 28."""
    from app.ml.forecaster import EWMA_LOOKBACK, load
    import app.engines.ml_features as mf

    load.cache_clear()
    m = load("")
    if m is None:
        pytest.skip("Chưa có mô hình LightGBM trong app/ml/artifacts")
    seen = {}
    real = mf.ewma_block

    def spy(Y, S, t, end, unit_k=1.0):
        seen["days"] = t + 1
        return real(Y, S, t, end, unit_k)

    monkeypatch.setattr(mf, "ewma_block", spy)
    m._cache.clear()
    m.forecast([8.0] * 90, [False] * 90, END, 7, (1, 10, 100))
    assert seen["days"] == EWMA_LOOKBACK == 56


# ---- dat hang: du bao phu het cua so tran HSD, ngoai tam thi lap tuan cuoi
def test_forecast_beyond_horizon_repeats_last_week():
    fc = _fc([float(i) for i in range(14)], method="ewma")
    assert [fc.at(14 + k) for k in range(8)] == [7.0, 8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 7.0]
    assert _fc([3.0, 4.0]).at(10) == 4.0  # chua du mot tuan: giu ngay cuoi


def test_forecast_horizon_covers_shelf_life_window():
    assert forecast_horizon(2, 7, 60) == 2 + 60 + 2
    assert forecast_horizon(1, 1, 365) == 1 + 90 + 2  # tran HSD chi xet toi da 90 ngay
    assert forecast_horizon(1, 7, 2) == 1 + 7 + 2


# ---- giam gia: keo them khach cho ca mat hang, nhu hai bo mo phong
def test_markdown_moves_a_lot_that_sells_nothing_at_full_price():
    inp = DispositionInput(qty=20, unit_cost=6000, unit_price=10000, days_left=2, expected_sold_full_price=0,
                           elasticity=3.0, daily_demand=5.0)
    md = [o for o in evaluate(inp) if o.action == "MARKDOWN"]
    assert md and all(o.units_sold > 0 and o.delta_vs_keep > 0 for o in md)


def test_markdown_unchanged_for_a_lot_that_covers_the_whole_demand():
    inp = DispositionInput(qty=40, unit_cost=6000, unit_price=10000, days_left=2, expected_sold_full_price=15,
                           elasticity=3.0, daily_demand=5.0)
    o = next(o for o in evaluate(inp) if o.action == "MARKDOWN" and o.markdown_pct == 0.2)
    assert o.units_sold == pytest.approx(15 * (1 + 3.0 * 0.2))


def test_evening_option_must_go_deeper_than_the_approved_one():
    inp = DispositionInput(qty=10, unit_cost=6000, unit_price=10000, days_left=0, expected_sold_full_price=2,
                           elasticity=3.0, daily_demand=5.0, current_evening=0.3)
    assert all(o.markdown_pct > 0.3 for o in evaluate(inp) if o.action == "MARKDOWN")


# ---- agent guard: so phai co that trong nguon, khong phai mot doan chu so bat ky
def test_guard_does_not_glue_neighbouring_numbers():
    src = ['{"qty": [12, 345], "value": 1250000}']
    assert check_answer("Giá trị 1.250.000đ", src).ok
    assert check_answer("Tổng 12.345 đơn vị", src).ungrounded_numbers == ["12.345"]  # truoc day "12345" khop
    assert check_answer("Giá trị 250.000đ", src).ungrounded_numbers == ["250.000"]  # doan con cua 1250000
    assert check_answer("Doanh thu 1.234.567đ", ["revenue: 1.234.567"]).ok


# ---- nhan nhom can date dung chung giua bao cao va bieu do
def test_overdue_bucket_label_is_shared_with_chart():
    assert bucket(-1) == OVERDUE == BUCKET_ORDER[0]
    assert bucket(0) == BUCKET_ORDER[1] and bucket(2) == "1-3 ngày"
