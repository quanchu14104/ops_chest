"""Dac trung cho mo hinh du bao LightGBM. DUNG CHUNG cho luc huan luyen (Kaggle) va luc chay that (OC).

Chi dung numpy + engine EWMA cua OC (thuan Python) de file nay chep thang len Kaggle duoc. Moi dac trung chi dung
thu cua hang that su biet tai thoi diem dat hang: nhu cau theo ngay (da quy ve gia goc), co het hang theo ngay,
lich (thu, ngay le), ma nhom hang, va DU BAO CUA ENGINE EWMA (mo hinh hoc cach sua sai cho engine cu).
KHONG dung thoi tiet cua ngay can du bao.

Don vi: chuoi dau vao o don vi luc huan luyen (so ban da quy doi cua FRN); `unit_k` quy ra don vi cua hang cho EWMA
(san Poisson cua EWMA phu thuoc don vi). Dich hoc la ty le y[t+h] / muc nen 28 ngay, nen mot mo hinh dung chung
cho moi quy mo ban.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

WINDOW = 28
MAX_H = 7
N_LAGS = 7
FEATURES = (
    [f"lag{i}" for i in range(1, N_LAGS + 1)]
    + ["mean3", "mean7", "mean14", "same_wd", "same_wd_last", "std28", "zero28", "stockout28", "stockout7",
       "days_since_stockout", "stockout_last", "trend", "log_level", "ewma_h", "ewma_sigma", "h", "target_wd",
       "origin_wd", "target_holiday", "mgmt_group", "cat1", "cat2"]
)
CATEGORICAL = ["target_wd", "origin_wd", "mgmt_group", "cat1", "cat2"]


def impute_stockouts(Y: np.ndarray, S: np.ndarray, weekday: np.ndarray) -> np.ndarray:
    """Ngay het hang: luong ban chi la can duoi cua nhu cau. Thay bang max(ban, TB cung thu cua ngay con hang)
    trong chinh cua so. Y, S: (n, W); weekday: (W,) thu cua tung cot."""
    Y = Y.astype(np.float64, copy=True)
    if not S.any():
        return Y
    for wd in range(7):
        cols = np.where(weekday == wd)[0]
        if cols.size == 0:
            continue
        y, s = Y[:, cols], S[:, cols]
        ok = ~s
        cnt = ok.sum(1)
        mean = np.where(cnt > 0, (y * ok).sum(1) / np.maximum(cnt, 1), np.nan)
        fill = np.where(np.isnan(mean)[:, None], y, np.maximum(y, mean[:, None]))
        Y[:, cols] = np.where(s, fill, y)
    return Y


def ewma_block(Y: np.ndarray, S: np.ndarray, t: int, end: date, unit_k: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Du bao cua engine EWMA cua OC cho h = 1..MAX_H tu moc t (cot cuoi da biet, ngay `end`).
    Tra ve (mid (n, MAX_H), sigma (n,)) o cung don vi voi Y. Chay engine o don vi cua hang (Y * unit_k)."""
    from app.engines.forecast import forecast_demand

    n = Y.shape[0]
    mid = np.zeros((n, MAX_H))
    sig = np.zeros(n)
    for i in range(n):
        fc = forecast_demand((Y[i, :t + 1] * unit_k).tolist(), end, MAX_H, stockout=S[i, :t + 1].tolist(), event_factors={})
        mid[i] = np.asarray(fc.daily) / unit_k
        sig[i] = fc.sigma_daily / unit_k
    return mid, sig


def build_features(
    Y: np.ndarray,
    S: np.ndarray,
    t: int,
    horizons: list[int] | range,
    weekday: np.ndarray,
    holiday: np.ndarray,
    statics: np.ndarray | None = None,
    ewma: tuple[np.ndarray, np.ndarray] | None = None,
    end: date | None = None,
    unit_k: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Dac trung cho moi chuoi, moc t (cot cuoi da biet), cac khoang cach h.

    Y, S: (n, T) nhu cau o gia goc / co het hang, T > t. weekday, holiday: (>= t + MAX_H + 1,) theo cot.
    statics: (n, 3) ma nhom (management_group, cat1, cat2), None = 0.
    ewma: (mid (n, MAX_H), sigma (n,)) da tinh san (huan luyen tinh song song); None = tinh tai cho (can `end`).
    Tra ve (X: (n*len(h), len(FEATURES)) float32, level: (n,)). Hang xep theo h roi theo chuoi.
    """
    n = Y.shape[0]
    if t < WINDOW - 1:
        raise ValueError(f"Can it nhat {WINDOW} ngay lich su (t={t}).")
    lo = t - WINDOW + 1
    wd = weekday[lo:t + 1]
    Yi = impute_stockouts(Y[:, lo:t + 1], S[:, lo:t + 1], wd)
    level = Yi.mean(1)
    scale = np.where(level > 0, level, 1.0)
    Sw = S[:, lo:t + 1]
    if statics is None:
        statics = np.zeros((n, 3))
    if ewma is None:
        if end is None:
            raise ValueError("Can `end` (ngay cua cot t) de tinh du bao EWMA.")
        ewma = ewma_block(Y, S, t, end, unit_k)
    e_mid, e_sig = ewma

    last_so = np.where(Sw.any(1), WINDOW - 1 - np.argmax(Sw[:, ::-1], axis=1), WINDOW)
    base = {
        "mean3": Yi[:, -3:].mean(1) / scale,
        "mean7": Yi[:, -7:].mean(1) / scale,
        "mean14": Yi[:, -14:].mean(1) / scale,
        "std28": Yi.std(1) / scale,
        "zero28": (Y[:, lo:t + 1] <= 0).mean(1),
        "stockout28": Sw.mean(1),
        "stockout7": Sw[:, -7:].mean(1),
        "days_since_stockout": last_so.astype(float),
        "stockout_last": Sw[:, -1].astype(float),
        "trend": (Yi[:, -7:].mean(1) - Yi[:, :7].mean(1)) / scale,  # tuan gan nhat so voi tuan dau cua so
        "log_level": np.log1p(level),
        "ewma_sigma": e_sig / scale,
        "origin_wd": np.full(n, weekday[t], dtype=float),
        "mgmt_group": statics[:, 0].astype(float),
        "cat1": statics[:, 1].astype(float),
        "cat2": statics[:, 2].astype(float),
    }
    for i in range(1, N_LAGS + 1):
        base[f"lag{i}"] = Yi[:, -i] / scale

    rows = []
    for h in horizons:
        if not 1 <= h <= MAX_H:
            raise ValueError(f"h phai trong 1..{MAX_H}")
        d = t + h
        tw = weekday[d]
        same = Yi[:, wd == tw]
        f = dict(base)
        f["same_wd"] = (same.mean(1) if same.shape[1] else Yi.mean(1)) / scale
        f["same_wd_last"] = Yi[:, d - 7 - lo] / scale  # cung thu tuan truoc (d - 7 <= t)
        f["ewma_h"] = e_mid[:, h - 1] / scale
        f["h"] = np.full(n, h, dtype=float)
        f["target_wd"] = np.full(n, tw, dtype=float)
        f["target_holiday"] = np.full(n, float(holiday[d]))
        rows.append(np.column_stack([f[c] for c in FEATURES]))
    return np.vstack(rows).astype(np.float32), level


def day_index(start: date, d: date) -> int:
    return (d - start).days


def dates_from(end: date, n: int, extra: int = MAX_H) -> list[date]:
    """n ngay ket thuc o `end`, cong them `extra` ngay tuong lai."""
    first = end - timedelta(days=n - 1)
    return [first + timedelta(days=i) for i in range(n + extra)]
