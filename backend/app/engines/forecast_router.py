"""Chon bo du bao cho tung mat hang: LightGBM (hoc tren FreshRetailNet-50K) hoac engine EWMA cu.

LightGBM chi duoc dung khi DU ca cac dieu kien:
  - cau hinh FORECAST_ENGINE=auto (mac dinh) va co file mo hinh;
  - mat hang co nhu cau tu FRN (biet ma nhom cua FRN, `frn_statics`);
  - co it nhat 28 ngay lich su va 28 ngay gan nhat co ban;
  - mat hang thuoc nhom ma tren diem ban giu lai LightGBM thang EWMA (meta.json: use_ml_segments).
Thieu mot dieu kien thi dung `forecast_demand` (EWMA) nhu cu. Hai bo cung tra ve `Forecast`; truong `method`
cho biet bo nao da du bao.
"""
from __future__ import annotations

from datetime import date

from app.engines.forecast import Forecast, forecast_demand


def forecast(history: list[float], history_end: date, horizon: int, stockout: list[bool] | None = None,
             start: date | None = None, event_factors: dict | None = None, skip_dates: set[date] | None = None,
             frn_statics: tuple[int, int, int] | None = None, model: str = "", holiday_of=None) -> Forecast:
    from app.config import settings

    if settings.forecast_engine == "auto" and frn_statics is not None:
        from app.ml.forecaster import load

        ml = load(model)
        if ml is not None and ml.eligible(history):
            return ml.forecast(history, stockout or [False] * len(history), history_end, horizon, frn_statics,
                               start=start, holiday_of=holiday_of)
    return forecast_demand(history, history_end, horizon, stockout=stockout, start=start,
                           event_factors=event_factors, skip_dates=skip_dates)
