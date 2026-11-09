"""Tinh so luong dat hang de xuat.

Hai che do:
- Hang de hu (HSD ngan hon chu ky dat + 7 ngay): bai toan newsvendor. Muc phuc vu toi uu
  = (gia - von) / (gia - gia_tri_thu_hoi), tuc can bang giua mat lai khi het hang va lo khi phai huy.
- Hang ben: order-up-to voi ton an toan z*sigma*sqrt(L+R), z lay theo o ABC-XYZ.

Ca hai deu:
- Mo phong FEFO ton hien co den ngay hang ve -> chi tinh phan ton CON HAN khi hang moi ve.
- Bi chan tran boi luong ban duoc truoc khi lo moi het han (tran HSD).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from statistics import NormalDist

from app.engines.forecast import Forecast


@dataclass
class LotState:
    qty: float
    expiry: date


@dataclass
class Incoming:
    qty: float
    arrival: date
    expiry: date


@dataclass
class ReplenishmentInput:
    today: date  # ngay dat hang
    lead_time_days: int
    review_period_days: int
    shelf_life_days: int
    forecast: Forecast  # forecast.start phai la today + 1
    lots: list[LotState]
    incoming: list[Incoming] = field(default_factory=list)
    pack_size: int = 1
    z: float = 1.65
    unit_cost: float = 0.0
    unit_price: float = 0.0
    salvage_per_unit: float = 0.0  # tien thu hoi ky vong/don vi khong ban duoc (giam gia, tra NCC)
    # Chi phi co hoi khi het hang ngoai phan lai mat (khach bo di, "chance loss"); cao voi hang keo khach
    stockout_penalty_per_unit: float = 0.0
    # Ngay dau tien con nhu cau phai tru vao ton: today+1 neu dat cuoi ngay (mac dinh),
    # = today neu dat buoi sang truoc gio ban (ung dung that). forecast.start nen trung ngay nay.
    first_demand_day: date | None = None


@dataclass
class ReplenishmentResult:
    qty: int
    raw_qty: float
    arrival_date: date
    mode: str  # perishable_newsvendor / order_up_to
    coverage_days: int
    demand_coverage: float
    projected_usable_at_arrival: float
    expected_waste_before_arrival: float
    served_by_existing: float
    safety_stock: float
    service_level: float
    shelf_life_cap: float
    capped_by_shelf_life: bool

    def to_dict(self) -> dict:
        d = asdict(self)
        d["arrival_date"] = self.arrival_date.isoformat()
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 2)
        return d


def _simulate_fefo(lots: list[list], start: date, days: int, demand_at) -> tuple[float, float, list[list]]:
    """lots: [[qty, expiry], ...] (bi sua tai cho). Tra ve (da ban, da huy, lots con lai)."""
    sold = waste = 0.0
    for k in range(days):
        d = start + timedelta(days=k)
        need = demand_at(d)
        lots.sort(key=lambda x: x[1])
        for lot in lots:
            if need <= 0:
                break
            if lot[1] < d or lot[0] <= 0:
                continue
            take = min(lot[0], need)
            lot[0] -= take
            need -= take
            sold += take
        for lot in lots:
            if lot[1] <= d and lot[0] > 0:
                waste += lot[0]
                lot[0] = 0
        lots[:] = [x for x in lots if x[0] > 0]
    return sold, waste, lots


def newsvendor_service_level(unit_cost: float, unit_price: float, salvage: float,
                             stockout_penalty: float = 0.0) -> float:
    under = max(unit_price - unit_cost + stockout_penalty, 0.01)  # mat lai + mat khach khi thieu
    over = max(unit_cost - salvage, 0.01)  # lo khi thua
    return min(0.98, max(0.3, under / (under + over)))


def compute_order(inp: ReplenishmentInput) -> ReplenishmentResult:
    fc = inp.forecast
    base = inp.first_demand_day or inp.today + timedelta(days=1)

    def demand_at(d: date) -> float:
        return fc.at((d - fc.start).days)

    arrival = inp.today + timedelta(days=max(inp.lead_time_days, 1))
    R = max(inp.review_period_days, 1)
    L = max(inp.lead_time_days, 1)
    new_expiry = arrival + timedelta(days=inp.shelf_life_days - 1)

    lots = [[float(l.qty), l.expiry] for l in inp.lots if l.qty > 0]
    # Don giao tre van la hang dang ve, neu khong se dat trung. Khong giao nua thi SM phai huy don.
    lots += [[float(inc.qty), inc.expiry] for inc in inp.incoming if inc.arrival < base]
    # 1) Mo phong tu ngay mai den truoc ngay hang moi ve (hang dang ve cung duoc cong vao)
    pre_days = (arrival - base).days
    pre_sold = pre_waste = 0.0
    for k in range(pre_days):
        d = base + timedelta(days=k)
        for inc in inp.incoming:
            if inc.arrival == d:
                lots.append([float(inc.qty), inc.expiry])
        s, w, lots = _simulate_fefo(lots, d, 1, demand_at)
        pre_sold += s
        pre_waste += w
    for inc in inp.incoming:
        if inc.arrival >= arrival:  # ve cung hoac sau ngay hang moi -> van la ton cho chu ky nay
            lots.append([float(inc.qty), inc.expiry])
    usable_at_arrival = sum(q for q, e in lots if e >= arrival)

    # 2) Trong chu ky phu (arrival .. arrival+R-1): ton cu phuc vu duoc bao nhieu?
    demand_cov = sum(demand_at(arrival + timedelta(days=k)) for k in range(R))
    lots_cov = [list(x) for x in lots]
    served, _, leftover_lots = _simulate_fefo(lots_cov, arrival, R, demand_at)
    leftover = sum(q for q, e in leftover_lots if e >= arrival + timedelta(days=R))
    unmet = max(0.0, demand_cov - served)

    perishable = inp.shelf_life_days <= R + 7
    sigma_cov = fc.sigma_daily * math.sqrt(R if perishable else L + R)
    if perishable:
        sl = newsvendor_service_level(inp.unit_cost, inp.unit_price, inp.salvage_per_unit,
                                      inp.stockout_penalty_per_unit)
        z = NormalDist().inv_cdf(sl)
        mode = "perishable_newsvendor"
    else:
        z = inp.z
        sl = NormalDist().cdf(z)
        mode = "order_up_to"
    safety = z * sigma_cov
    raw = unmet + safety - leftover

    # 3) Tran HSD: luong lo moi co the ban duoc truoc new_expiry
    window = min(90, max(1, (new_expiry - arrival).days + 1))  # >90 ngay thi tran HSD khong con rang buoc
    demand_window = sum(demand_at(arrival + timedelta(days=k)) for k in range(window))
    lots_win = [list(x) for x in lots]
    served_win, _, _ = _simulate_fefo(lots_win, arrival, window, demand_at)
    z_cap = max(z, 0.0) if perishable else max(z, 1.0)
    cap = max(0.0, demand_window - served_win) + z_cap * fc.sigma_daily * math.sqrt(window)
    capped = raw > cap
    qty_f = max(0.0, min(raw, cap))

    pack = max(1, inp.pack_size)
    if qty_f <= 0:
        qty = 0
    elif perishable:
        qty = int(round(qty_f / pack)) * pack  # lam tron gan nhat de tranh du thua hang tuoi
    else:
        qty = int(math.ceil(qty_f / pack - 1e-9)) * pack

    return ReplenishmentResult(
        qty=qty,
        raw_qty=raw,
        arrival_date=arrival,
        mode=mode,
        coverage_days=R,
        demand_coverage=demand_cov,
        projected_usable_at_arrival=usable_at_arrival,
        expected_waste_before_arrival=pre_waste,
        served_by_existing=served,
        safety_stock=safety,
        service_level=sl,
        shelf_life_cap=cap,
        capped_by_shelf_life=capped,
    )


def review_period(order_weekdays: list[int], today: date) -> int:
    """So ngay tu lan dat hom nay toi lan dat ke tiep theo lich NCC."""
    if not order_weekdays:
        return 7
    for k in range(1, 8):
        if (today + timedelta(days=k)).weekday() in order_weekdays:
            return k
    return 7
