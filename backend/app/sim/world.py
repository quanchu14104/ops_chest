"""Tham so cua 'the gioi gia lap': khach hang THAT phan ung the nao.

Tach rieng khoi engine co chu y. Engine (disposition.ELASTICITY) la dieu Ops Chest GIA DINH; WorldParams
la dieu xay ra trong mo phong. Neu hai ben dung chung mot hang so thi backtest tu chung minh chinh no:
engine luon doan dung phan ung cua khach. File nay vi vay KHONG duoc import tu app.engines.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# So nhan la ti le so voi muc Ops Chest gia dinh (FRESH 3,0 / SHORT 2,0 / LONG 1,2).
_ASSUMED_BY_ENGINE_AT_DESIGN_TIME = {"FRESH": 3.0, "SHORT": 2.0, "LONG": 1.2}


@dataclass(frozen=True)
class WorldParams:
    elasticity: dict[str, float] = field(default_factory=lambda: dict(_ASSUMED_BY_ENGINE_AT_DESIGN_TIME))
    evening_share: float = 0.3  # ty trong luot khach sau 18h
    # Ty le luot mua lay dung lo gan het han. Engine gia dinh 100%; khach that hay lay lo moi o phia sau ke.
    fefo_compliance: float = 1.0

    def scaled(self, factor: float) -> "WorldParams":
        return replace(self, elasticity={k: v * factor for k, v in self.elasticity.items()})

    def with_fefo(self, compliance: float) -> "WorldParams":
        return replace(self, fefo_compliance=compliance)


OPTIMISTIC_WORLD = WorldParams()  # khach phan ung dung nhu engine gia dinh (truong hop tot nhat cho B)
# Tham chieu: khach chi phan ung bang mot nua gia dinh -> engine bi sai mo hinh, dung nhu ngoai doi.
REFERENCE_WORLD = OPTIMISTIC_WORLD.scaled(0.5)
PESSIMISTIC_WORLD = OPTIMISTIC_WORLD.scaled(0.25)
