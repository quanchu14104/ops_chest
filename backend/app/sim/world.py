"""Tham so cua 'the gioi gia lap': khach hang THAT phan ung the nao.

Tach rieng khoi engine co chu y. Engine (disposition.ELASTICITY) la dieu Ops Chest GIA DINH; WorldParams
la dieu xay ra trong mo phong. Neu hai ben dung chung mot hang so thi backtest tu chung minh chinh no:
engine luon doan dung phan ung cua khach. File nay vi vay KHONG duoc import tu app.engines.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# So nhan la ti le so voi muc Ops Chest gia dinh (FRESH 3,0 / SHORT 2,0 / LONG 1,2).
_ASSUMED_BY_ENGINE_AT_DESIGN_TIME = {"FRESH": 3.0, "SHORT": 2.0, "LONG": 1.2}

# Ty trong khach THAT theo khung gio (sang 6-11, trua 11-14, chieu 14-17, toi 17-22). Co y lech nhe so voi bang
# cua hang khai bao (sim/catalog.py ENGINE_DAYPARTS): com hop dinh trua manh hon, banh mi dinh sang manh hon.
_DAYPARTS = ((6, 11), (11, 14), (14, 17), (17, 22))
_DEFAULT_SHARES = (0.2, 0.2, 0.225, 0.375)  # sau 18h = 0,3
TRUE_DAYPARTS = {
    "Cơm hộp & cơm nắm": (0.15, 0.55, 0.12, 0.18),
    "Bánh mì, sandwich & bánh bao": (0.55, 0.2, 0.08, 0.17),
    "Salad, trái cây & xôi": (0.3, 0.4, 0.12, 0.18),
}


def _after(shares, hour: int) -> float:
    total = 0.0
    for (a, b), s in zip(_DAYPARTS, shares):
        if hour <= a:
            total += s
        elif hour < b:
            total += s * (b - hour) / (b - a)
    return total


@dataclass(frozen=True)
class WorldParams:
    elasticity: dict[str, float] = field(default_factory=lambda: dict(_ASSUMED_BY_ENGINE_AT_DESIGN_TIME))
    dayparts: dict = field(default_factory=lambda: dict(TRUE_DAYPARTS))
    # Ty le luot mua lay dung lo gan het han. Engine gia dinh 100%; khach that hay lay lo moi o phia sau ke.
    fefo_compliance: float = 1.0

    def share_after(self, category: str, hour: int = 18) -> float:
        """Ty trong khach trong ngay den tu `hour` tro di (khach con lai khi bat dau giam gia)."""
        return _after(self.dayparts.get(category, _DEFAULT_SHARES), hour)

    def scaled(self, factor: float) -> "WorldParams":
        return replace(self, elasticity={k: v * factor for k, v in self.elasticity.items()})

    def with_fefo(self, compliance: float) -> "WorldParams":
        return replace(self, fefo_compliance=compliance)


OPTIMISTIC_WORLD = WorldParams()  # khach phan ung dung nhu engine gia dinh (truong hop tot nhat cho B)
# Tham chieu: khach chi phan ung bang mot nua gia dinh -> engine bi sai mo hinh, dung nhu ngoai doi.
REFERENCE_WORLD = OPTIMISTIC_WORLD.scaled(0.5)
PESSIMISTIC_WORLD = OPTIMISTIC_WORLD.scaled(0.25)


def frn_world(store_id: int | None = None) -> WorldParams:
    """The gioi cho cua hang chay nhu cau FreshRetailNet-50K: nhu cau THAT (FRN), khung gio ban cua chinh diem do (FRN).
    Phan ung cua khach voi giam gia cua OC van la tham chieu cu (50% muc engine gia dinh): FRN khong cho uoc luong
    duoc do co gian dang tin (gia noi sinh, xem docs/ml-frn.md), nen khong dung so do."""
    from app.sim import frn
    from app.sim.frn_catalog import category_name

    e = REFERENCE_WORLD.elasticity["FRESH"]
    shares = (frn.dayparts().get("world_by_store") or {}).get(str(store_id if store_id is not None else frn.demo_store_id()), {})
    return WorldParams(elasticity={"FRESH": e, "SHORT": e, "LONG": e},
                       dayparts={category_name(int(g)): tuple(v) for g, v in shares.items()})
