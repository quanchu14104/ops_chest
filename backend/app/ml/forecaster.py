"""Du bao bang LightGBM da huan luyen tren FreshRetailNet-50K (ml/kaggle/train_frn.py), chay trong OC.

Tra ve dung kieu `Forecast` cua engine EWMA, nen dat hang, can date, de xuat... khong phai sua gi.
Dac trung tinh bang `app.engines.ml_features` - CUNG file da dung luc huan luyen tren Kaggle.

Don vi: OC tinh theo don vi hang; mo hinh hoc tren so ban da quy doi cua FRN. Chia cho K truoc khi tinh dac
trung, nhan K vao ket qua.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.engines.forecast import Forecast
from app.engines.ml_features import FEATURES, MAX_H, WINDOW, build_features

ARTIFACTS = Path(__file__).parent / "artifacts"
Z90 = 1.2815515655446004
METHOD = "lightgbm_frn"


class MlForecaster:
    def __init__(self, art_dir: Path = ARTIFACTS, prefix: str = ""):
        import lightgbm as lgb

        self.meta = json.loads((art_dir / "meta.json").read_text(encoding="utf-8"))
        if list(self.meta["features"]) != list(FEATURES):
            raise RuntimeError("Mô hình được huấn luyện với bộ đặc trưng khác ml_features.py hiện tại.")
        self.k = float(self.meta["k_scale"])
        # Đọc qua chuỗi và chuẩn hóa xuống dòng: checkout trên Windows có thể đổi LF→CRLF,
        # và LightGBM sập cả tiến trình (không bắt được) khi đọc file mô hình có CRLF.
        self.models = {
            q: lgb.Booster(model_str=(art_dir / f"{prefix}q{q}.txt").read_bytes().decode("ascii").replace("\r\n", "\n"))
            for q in (10, 50, 90)
        }
        self.prefix = prefix
        cuts = self.meta.get("segment_cuts_oc_units") or [math.inf, math.inf]
        self.cuts = (float(cuts[0]), float(cuts[1]))
        self.zero_cut = float(self.meta.get("intermittent_zero_share", 0.3))
        self.use_ml = set(self.meta.get("use_ml_segments", []))
        self._cache: dict = {}

    # ---- nhom hang: ML chi duoc dung o nhom no thang engine cu tren diem ban giu lai
    def segment(self, history: list[float]) -> str:
        recent = history[-90:]
        level = sum(recent) / len(recent) if recent else 0.0
        zero = sum(1 for x in recent if x <= 0) / len(recent) if recent else 1.0
        vol = "ban_it" if level <= self.cuts[0] else ("ban_vua" if level <= self.cuts[1] else "ban_chay")
        return f"{vol}|{'lat_nhat' if zero > self.zero_cut else 'deu'}"

    def eligible(self, history: list[float]) -> bool:
        return len(history) >= WINDOW and sum(history[-WINDOW:]) > 0 and self.segment(history) in self.use_ml

    # ---- du bao 7 ngay tiep theo cua nhieu chuoi mot luc
    def _predict_block(self, Y: np.ndarray, S: np.ndarray, end: date, statics: np.ndarray, holiday_of) -> tuple:
        n, T = Y.shape
        first = end - timedelta(days=T - 1)
        days = [first + timedelta(days=i) for i in range(T + MAX_H)]
        weekday = np.array([d.weekday() for d in days])
        holiday = np.array([float(holiday_of(d)) for d in days])
        # Chuoi `demand` cua OC da o gia goc; EWMA (dac trung) chay o don vi cua hang nhu luc huan luyen
        X, level = build_features(Y / self.k, S, T - 1, range(1, MAX_H + 1), weekday, holiday, statics,
                                  end=end, unit_k=self.k)
        out = {}
        for q, m in self.models.items():
            out[q] = np.maximum(m.predict(X).reshape(MAX_H, n).T, 0) * level[:, None] * self.k
        lo = np.minimum(out[10], out[50])
        hi = np.maximum(out[90], out[50])
        return lo, out[50], hi, level * self.k

    def forecast(self, history: list[float], stockout: list[bool], history_end: date, horizon: int,
                 statics: tuple[int, int, int], start: date | None = None, holiday_of=None) -> Forecast:
        """Du bao nhu cau o gia goc, `horizon` ngay tu `start` (mac dinh ngay sau history_end)."""
        start = start or history_end + timedelta(days=1)
        holiday_of = holiday_of or (lambda d: d.weekday() >= 5)
        y = [float(x) for x in history[-WINDOW:]]
        s = [bool(x) for x in (stockout or [False] * len(history))[-WINDOW:]]
        key = (self.prefix, history_end, tuple(statics), tuple(y), tuple(s))
        hit = self._cache.get(key)
        if hit is None:
            hit = self._predict_block(np.array([y]), np.array([s]), history_end, np.array([statics]), holiday_of)
            if len(self._cache) > 50_000:
                self._cache.clear()
            self._cache[key] = hit
        lo, mid, hi, level = (hit[0][0], hit[1][0], hit[2][0], float(hit[3][0]))
        by_wd = {(history_end + timedelta(days=h)).weekday(): float(mid[h - 1]) for h in range(1, MAX_H + 1)}
        daily = []
        for k in range(horizon):
            d = start + timedelta(days=k)
            off = (d - history_end).days
            daily.append(float(mid[off - 1]) if 1 <= off <= MAX_H else by_wd[d.weekday()])
        sigma = float(np.mean((hi - lo) / (2 * Z90)))
        mean_wd = sum(by_wd.values()) / 7 or 1.0
        return Forecast(start=start, daily=daily, sigma_daily=max(sigma, 0.1), level=level,
                        weekday_index=[round(by_wd[w] / mean_wd, 3) if mean_wd else 1.0 for w in range(7)],
                        n_obs=len(history), n_censored=sum(1 for x in stockout or [] if x), method=METHOD)


@lru_cache(maxsize=4)
def load(prefix: str = "", art_dir: str | None = None) -> MlForecaster | None:
    d = Path(art_dir) if art_dir else ARTIFACTS
    if not (d / "meta.json").exists() or not (d / f"{prefix}q50.txt").exists():
        return None
    try:
        return MlForecaster(d, prefix)
    except Exception as e:  # noqa: BLE001 - thieu lightgbm / file hong: quay ve engine cu, khong lam sap app
        print(f"[ml] Không nạp được mô hình LightGBM ({e}); dùng engine EWMA.")
        return None
