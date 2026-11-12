"""Chon bo du bao cho tung mat hang: LightGBM (hoc tren FreshRetailNet-50K) hoac engine EWMA cu.

LightGBM chi duoc dung khi DU ca cac dieu kien:
  - cau hinh FORECAST_ENGINE=auto (mac dinh) va co file mo hinh;
  - mat hang co nhu cau tu FRN (biet ma nhom cua FRN, `frn_statics`);
  - co it nhat 28 ngay lich su va 28 ngay gan nhat co ban;
  - mat hang thuoc nhom duoc dung ML. Co `decision_gate.json` thi nhom = segment x quy mo diem ban, chon theo LAI
    ngoai mau trong backtest FRN; khong co thi theo meta.json `use_ml_segments` (chon theo sai so du bao).
Thieu mot dieu kien thi dung `forecast_demand` (EWMA) nhu cu. Hai bo cung tra ve `Forecast`; truong `method`
cho biet bo nao da du bao.
"""
from __future__ import annotations

from datetime import date

from app.engines.forecast import Forecast, forecast_demand


def forecast(history: list[float], history_end: date, horizon: int, stockout: list[bool] | None = None,
             start: date | None = None, event_factors: dict | None = None, skip_dates: set[date] | None = None,
             frn_statics: tuple[int, int, int] | None = None, model: str = "", holiday_of=None,
             store_size: int | None = None, gate: dict | None = None) -> Forecast:
    """store_size: so mat hang FRN cua diem ban (bac quy mo trong bo chon). gate: bo chon tam (backtest),
    None = doc decision_gate.json / meta.json."""
    from app.config import settings

    if settings.forecast_engine == "auto" and frn_statics is not None:
        from app.ml.forecaster import load

        ml = load(model)
        if ml is not None and ml.eligible(history, store_size=store_size, gate=gate):
            return ml.forecast(history, stockout or [False] * len(history), history_end, horizon, frn_statics,
                               start=start, holiday_of=holiday_of, asymmetric=ml.asymmetric(gate))
    return forecast_demand(history, history_end, horizon, stockout=stockout, start=start,
                           event_factors=event_factors, skip_dates=skip_dates)
