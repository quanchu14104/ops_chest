"""Mo hinh nhu cau gia lap. Tat dinh theo (seed, sku, ngay) de backtest A/B gap CUNG nhu cau."""
from __future__ import annotations

import math
import random
import zlib
from datetime import date

from app.engines.calendar import tet_phase
from app.sim.catalog import ProductSpec

WEEKDAY = {
    "office_food": [1.15, 1.15, 1.15, 1.15, 1.1, 0.75, 0.6],
    "bakery": [1.05, 1.05, 1.05, 1.05, 1.05, 0.9, 0.85],
    "beer": [0.8, 0.8, 0.85, 0.9, 1.2, 1.45, 1.2],
    "snack": [0.9, 0.9, 0.95, 0.95, 1.1, 1.2, 1.1],
    "candy": [0.9, 0.9, 0.95, 0.95, 1.1, 1.2, 1.1],
    "ice_cream": [0.9, 0.9, 0.95, 0.95, 1.05, 1.2, 1.15],
    "water": [1.0, 1.0, 1.0, 1.0, 1.05, 1.05, 0.95],
    "soft_drink": [1.0, 1.0, 1.0, 1.0, 1.05, 1.1, 1.0],
    "tea_energy": [1.0, 1.0, 1.0, 1.0, 1.05, 1.05, 0.95],
    "coffee": [1.1, 1.1, 1.1, 1.1, 1.05, 0.85, 0.75],
}
SEASON_AMP = {"water": 0.2, "soft_drink": 0.2, "tea_energy": 0.2, "beer": 0.15, "ice_cream": 0.3,
              "coffee": 0.08}
HOT_SENSITIVE = {"water", "soft_drink", "tea_energy", "ice_cream", "beer"}
TET = {
    "pre_tet": {"beer": 1.8, "soft_drink": 1.5, "candy": 1.8, "snack": 1.4, "dry_goods": 1.5,
                "water": 1.2, "office_food": 0.9, "_": 1.0},
    "tet": {"office_food": 0.3, "bakery": 0.5, "dairy": 0.6, "beer": 1.2, "soft_drink": 0.9, "_": 0.6},
    "post_tet": {"office_food": 0.7, "_": 0.85},
}
PROMO_GROUPS = {"soft_drink", "tea_energy", "coffee", "beer", "snack", "candy", "noodle"}


def _rng(*parts) -> random.Random:
    key = "|".join(str(p) for p in parts).encode()
    return random.Random(zlib.crc32(key))


def weather(seed: int, d: date) -> tuple[bool, bool]:
    """(nang nong, mua) theo mua mien Nam."""
    r = _rng(seed, "wx", d.isoformat())
    m = d.month
    if m in (3, 4, 5):
        p_hot, p_rain = 0.45, 0.1
    elif 6 <= m <= 10:
        p_hot, p_rain = 0.15, 0.5
    else:
        p_hot, p_rain = 0.1, 0.1
    return r.random() < p_hot, r.random() < p_rain


def is_promo(seed: int, p: ProductSpec, d: date) -> bool:
    if p.group not in PROMO_GROUPS:
        return False
    iso = d.isocalendar()
    return _rng(seed, "promo", p.sku, iso.year, iso.week).random() < 0.05


def expected_demand(seed: int, p: ProductSpec, d: date) -> float:
    lam = p.base_rate
    lam *= WEEKDAY.get(p.group, [1.0] * 7)[d.weekday()]
    amp = SEASON_AMP.get(p.group, 0.03)
    lam *= 1 + amp * math.cos(2 * math.pi * (d.timetuple().tm_yday - 110) / 365.25)
    hot, rain = weather(seed, d)
    if hot and p.group in HOT_SENSITIVE:
        lam *= 1.3
    if rain:
        lam *= 1.2 if p.group == "noodle" else (1.1 if p.group == "household" else 0.85)
    ph = tet_phase(d)
    if ph:
        table = TET[ph]
        lam *= table.get(p.group, table["_"])
    if is_promo(seed, p, d):
        lam *= 1.6
    return lam


def _poisson(r: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 40:
        return max(0, int(round(r.gauss(lam, math.sqrt(lam)))))
    L = math.exp(-lam)
    k, prod = 0, r.random()
    while prod > L:
        k += 1
        prod *= r.random()
    return k


def sample_demand(seed: int, p: ProductSpec, d: date) -> int:
    r = _rng(seed, "dem", p.sku, d.toordinal())
    lam = expected_demand(seed, p, d)
    k = p.dispersion_k
    lam *= r.gammavariate(k, 1.0 / k)  # tron gamma -> phan phoi nhi thuc am (qua phan tan)
    return _poisson(r, lam)


class DemandSource:
    """Nguon nhu cau cua 'the gioi' mo phong: `need` = so khach muon mua (nguyen), `expected` = muc ky vong (de
    tinh luong khach tang them khi giam gia)."""

    name = "synthetic"

    def need(self, p: ProductSpec, d: date) -> int:
        raise NotImplementedError

    def expected(self, p: ProductSpec, d: date) -> float:
        raise NotImplementedError


class SyntheticDemand(DemandSource):
    """Mo hinh gia lap cu (chi con dung cho bo test quy tac nghiep vu: Tet, hang dai ngay, lich nghi NCC)."""

    name = "synthetic"

    def __init__(self, seed: int = 7):
        self.seed = seed

    def need(self, p: ProductSpec, d: date) -> int:
        return sample_demand(self.seed, p, d)

    def expected(self, p: ProductSpec, d: date) -> float:
        return expected_demand(self.seed, p, d)


class FrnRangeError(ValueError):
    pass


class FrnDemand(DemandSource):
    """Nhu cau THAT cua mot diem ban FreshRetailNet-50K (da khoi phuc ngay het hang), quy ra don vi bang K."""

    name = "frn"

    def __init__(self, store, k: float):
        self.store = store
        self.k = k

    def _value(self, p: ProductSpec, d: date) -> float:
        i = self.store.day_index(d)
        if i is None:
            raise FrnRangeError(f"Hết dữ liệu FRN: chỉ có nhu cầu từ {self.store.dates[0]} đến {self.store.dates[-1]}.")
        return self.store.series[p.frn_id].demand[i] * self.k

    def need(self, p: ProductSpec, d: date) -> int:
        return int(round(self._value(p, d)))

    def expected(self, p: ProductSpec, d: date) -> float:
        return self._value(p, d)
