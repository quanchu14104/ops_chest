"""Du bao nhu cau theo ngay: muc nen (EWMA) x he so thu trong tuan x he so su kien (Tet).

Chon phuong phap don gian, giai thich duoc truoc hoi dong.

Nhu cau bi chan (censored demand): ngay het hang thi doanh so = luong ton, nhu cau that >= doanh so.
Bo han nhung ngay nay se lam du bao LECH THAP (vi do la ngay ban chay). Thay vao do ta uoc luong
E[D | D >= doanh so] theo phan phoi chuan (kieu Tobit) va lap vai vong.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import NormalDist

from app.engines.calendar import PHASES, tet_phase

_N = NormalDist()


@dataclass
class Forecast:
    start: date
    daily: list[float]
    sigma_daily: float
    level: float
    weekday_index: list[float]
    event_factors: dict[str, float] = field(default_factory=dict)
    n_obs: int = 0
    n_censored: int = 0
    method: str = "ewma_weekday_censored"
    adjustments: list[dict] = field(default_factory=list)  # gia thuyet cua SM da ap vao du bao

    def total(self, offset: int, days: int) -> float:
        return sum(self.at(offset + i) for i in range(days))

    def at(self, offset: int) -> float:
        if offset < 0:
            offset = 0
        if offset < len(self.daily):
            return self.daily[offset]
        return self.daily[-1] if self.daily else 0.0


def estimate_event_factors(history: list[float], end: date) -> dict[str, float]:
    """Hoc he so Tet tu lich su cua chinh SKU: TB ban trong giai doan / TB 28 ngay truoc do."""
    n = len(history)
    dates = [end - timedelta(days=n - 1 - i) for i in range(n)]
    by_phase: dict[str, list[float]] = {p: [] for p in PHASES}
    for d, v in zip(dates, history):
        ph = tet_phase(d)
        if ph:
            by_phase[ph].append(v)
    first_pre = next((i for i, d in enumerate(dates) if tet_phase(d) == "pre_tet"), None)
    if first_pre is None or first_pre < 28:
        return {p: 1.0 for p in PHASES}
    base = sum(history[first_pre - 28 : first_pre]) / 28
    factors: dict[str, float] = {}
    for p in PHASES:
        vals = by_phase[p]
        if base <= 0 or len(vals) < 3:
            factors[p] = 1.0
        else:
            factors[p] = round(max(0.1, min(4.0, (sum(vals) / len(vals)) / base)), 3)
    return factors


def baseline_demand(sold: float, discounted_units: float, discount_pct: float, evening_units: float,
                    elasticity: float) -> float:
    """Nhu cau o gia goc cua mot ngay, tu nhung gi cua hang quan sat duoc.

    Hang ban nho giam gia khong phai nhu cau binh thuong: tinh ca vao thi du bao bi thoi len, dat du,
    roi lai phai giam gia tiep. Ban gio vang la xa hang du nen bo han; ban giam gia ca ngay thi chia
    cho he so kich cau (1 + co gian * muc giam). Dung co gian GIA DINH vi cua hang khong biet so that.
    """
    full_price = max(0.0, sold - discounted_units - evening_units)
    return full_price + discounted_units / (1 + max(0.0, elasticity * discount_pct))


def _fit(obs: list[list], half_life_days: float) -> tuple[float, list[float], float]:
    """obs: [age, value, weekday, censored]. Tra ve (level, weekday_index, sigma)."""
    overall = sum(o[1] for o in obs) / len(obs)
    idx = [1.0] * 7
    if overall > 0:
        trust = min(1.0, overall / 2.0)  # SKU ban it -> tin he so thu it hon
        for w in range(7):
            vals = [o[1] for o in obs if o[2] == w]
            if len(vals) >= 2:
                idx[w] = 1.0 + ((sum(vals) / len(vals)) / overall - 1.0) * trust
        mean_idx = sum(idx) / 7
        idx = [x / mean_idx for x in idx]
    decay = math.log(2) / half_life_days
    wsum = vsum = 0.0
    for age, v, wd, _ in obs:
        w = math.exp(-decay * age)
        wsum += w
        vsum += w * (v / idx[wd] if idx[wd] > 0 else v)
    level = vsum / wsum if wsum else 0.0
    # Tinh tren MOI quan sat (ngay het hang da duoc noi suy): neu chi dung ngay khong het hang thi
    # sigma bi lech nho vi do toan la ngay ban it. San Poisson: phuong sai >= trung binh.
    resid = [o[1] - level * idx[o[2]] for o in obs]
    var = sum(r * r for r in resid) / max(1, len(resid) - 1)
    sigma = max(math.sqrt(var), math.sqrt(max(level, 0.0)), 0.1)
    return level, idx, sigma


def forecast_demand(
    history: list[float],
    history_end: date,
    horizon: int,
    stockout: list[bool] | None = None,
    start: date | None = None,
    event_factors: dict[str, float] | None = None,
    lookback: int = 56,
    half_life_days: float = 14.0,
    skip_dates: set[date] | None = None,
) -> Forecast:
    """history[i] la luong ban ngay (history_end - len+1+i). Tra ve du bao `horizon` ngay tu `start`.

    `skip_dates`: ngay co su kien SM da khai bao; khong dung de uoc luong muc nen (giong cach xu ly Tet).
    """
    start = start or history_end + timedelta(days=1)
    n = len(history)
    stockout = stockout or [False] * n
    if event_factors is None:
        event_factors = estimate_event_factors(history, history_end) if n >= 120 else {}

    lo = max(0, n - lookback)
    obs: list[list] = []
    for i in range(lo, n):
        d = history_end - timedelta(days=n - 1 - i)
        if tet_phase(d) or (skip_dates and d in skip_dates):
            continue
        obs.append([n - 1 - i, float(history[i]), d.weekday(), bool(stockout[i])])
    raw_sales = [o[1] for o in obs]
    n_cens = sum(1 for o in obs if o[3])

    if not obs:
        recent = [float(x) for x in history[lo:]] or [0.0]
        level = sum(recent) / len(recent)
        idx = [1.0] * 7
        sigma = max(math.sqrt(max(level, 0.0)), 0.1)
    else:
        level, idx, sigma = _fit(obs, half_life_days)
        if n_cens:
            for _ in range(3):
                for o, s in zip(obs, raw_sales):
                    if not o[3]:
                        continue
                    e = level * idx[o[2]]
                    a = (s - e) / sigma
                    tail = max(1e-3, 1 - _N.cdf(a))
                    o[1] = max(s, e + sigma * _N.pdf(a) / tail)
                level, idx, sigma = _fit(obs, half_life_days)

    daily = []
    for k in range(horizon):
        d = start + timedelta(days=k)
        f = level * idx[d.weekday()]
        ph = tet_phase(d)
        if ph:
            f *= event_factors.get(ph, 1.0)
        daily.append(max(0.0, f))

    return Forecast(
        start=start,
        daily=daily,
        sigma_daily=sigma,
        level=level,
        weekday_index=[round(x, 3) for x in idx],
        event_factors=event_factors,
        n_obs=len(obs),
        n_censored=n_cens,
    )


def hypothesis_verdict(factor: float, ratio: float, supply_limited: bool = False) -> str:
    """Cham gia thuyet: nhu cau thuc te da di duoc bao nhieu phan quang duong SM du doan so voi du bao nen.

    `supply_limited`: het hang nhieu trong khoang cham. Luc do doanh so chi la can duoi cua nhu cau, nen chi ket luan
    duoc dieu can duoi chung minh: bieu tang "dung", du bao giam "sai". Nhap it roi ban it khong chung minh duoc gi.
    """
    gap = factor - 1.0
    if abs(gap) < 1e-9:
        return "PARTIAL"
    share = (ratio - 1.0) / gap
    verdict = "CORRECT" if share >= 0.5 else ("WRONG" if share <= 0.25 else "PARTIAL")
    if supply_limited and verdict != ("CORRECT" if factor > 1 else "WRONG"):
        return "INCONCLUSIVE"
    return verdict


def wape(actual: list[float], predicted: list[float]) -> float | None:
    """Weighted Absolute Percentage Error: sum|a-f| / sum(a)."""
    denom = sum(actual)
    if denom <= 0:
        return None
    return sum(abs(a - f) for a, f in zip(actual, predicted)) / denom
