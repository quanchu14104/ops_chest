"""Chon bo du bao cho tung mat hang: LightGBM (hoc tren FreshRetailNet-50K) hoac engine EWMA cu.

LightGBM chi duoc dung khi DU ca cac dieu kien:
  - cau hinh FORECAST_ENGINE=auto (mac dinh) va co file mo hinh;
  - mat hang co nhu cau tu FRN (biet ma nhom cua FRN, `frn_statics`);
  - co it nhat 28 ngay lich su va 28 ngay gan nhat co ban;
  - mat hang thuoc nhom duoc dung ML. Co `decision_gate.json` thi nhom = segment x quy mo diem ban, chon theo LAI
    ngoai mau trong backtest FRN; khong co thi theo meta.json `use_ml_segments` (chon theo sai so du bao).
Bo chon cung quyet dinh do lech chuan dung de dat hang: cua LightGBM (doi xung / lech) hay cua EWMA.
Thieu mot dieu kien thi dung `forecast_demand` (EWMA) nhu cu. Hai bo cung tra ve `Forecast`; truong `method`
cho biet bo nao da du bao.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.engines.forecast import Forecast, forecast_demand


def mask_event_days(history: list[float], stockout: list[bool], history_end: date,
                    skip_dates: set[date] | None) -> tuple[list[float], list[bool]]:
    """Ngay SM da khai bao su kien (gia thuyet): luong ban la cua su kien, khong phai nhu cau thuong.

    EWMA bo han cac ngay nay. LightGBM can chuoi lien tuc (lag, TB 3/7/14 ngay), nen thay bang TB cua toi da 4 ngay
    binh thuong (khong su kien, con hang) cung thu gan nhat; khong co thi TB 14 ngay binh thuong gan nhat. Neu de
    nguyen, ngay tang vot lot vao lag, du bao bi day len trong khi gia thuyet con nhan he so lan nua."""
    if not skip_dates:
        return history, stockout
    n = len(history)
    days = [history_end - timedelta(days=n - 1 - i) for i in range(n)]
    hit = [d in skip_dates for d in days]
    if not any(hit):
        return history, stockout
    clean = [i for i in range(n) if not hit[i] and not stockout[i]]
    if not clean:
        return history, stockout
    y, s = list(history), list(stockout)
    for i in (i for i in range(n) if hit[i]):
        near = sorted(clean, key=lambda j: abs(j - i))
        same = [j for j in near if (j - i) % 7 == 0][:4]
        pool = same or near[:14]
        y[i] = sum(float(history[j]) for j in pool) / len(pool)
        s[i] = False
    return y, s


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
        y, s = mask_event_days(history, stockout or [False] * len(history), history_end, skip_dates)
        if ml is not None and ml.eligible(y, store_size=store_size, gate=gate):
            fc = ml.forecast(y, s, history_end, horizon, frn_statics,
                             start=start, holiday_of=holiday_of, asymmetric=ml.asymmetric(gate))
            if ml.sigma_mode(gate) == "ewma_sigma":
                # Du bao diem cua LightGBM, do lech chuan cua EWMA (hep hon): khoang rong cua LightGBM qua san
                # muc phuc vu 90-95% thanh dat du va huy nhieu hon (docs/ml-frn.md, muc 5.7)
                ewma = forecast_demand(history, history_end, horizon, stockout=stockout, start=start,
                                       event_factors=event_factors, skip_dates=skip_dates)
                fc.sigma_daily, fc.sigma_lo, fc.sigma_hi = ewma.sigma_daily, None, None
            return fc
    return forecast_demand(history, history_end, horizon, stockout=stockout, start=start,
                           event_factors=event_factors, skip_dates=skip_dates)
