"""Tinh so luong dat hang de xuat.

Hai che do:
- Hang de hu (HSD ngan hon chu ky dat + 7 ngay): bai toan newsvendor. Muc phuc vu toi uu
  = (gia - von) / (gia - gia_tri_thu_hoi), tuc can bang giua mat lai khi het hang va lo khi phai huy.
- Hang ben: order-up-to voi ton an toan z*sigma*sqrt(L+R), z lay theo o ABC-XYZ.

Ca hai deu:
- Mo phong FEFO ton hien co den ngay hang ve -> chi tinh phan ton CON HAN khi hang moi ve.
- Bi chan tran boi luong ban duoc truoc khi lo moi het han (tran HSD) va boi suc chua ke/tu.
- Co SAN muc phuc vu theo vai tro mat hang (hang keo khach, nhom A, con lai): khach vao cua hang tien loi
  vi tin la co hang, nen engine khong duoc chu dong de thieu hang chi vi lai thap.
- Ngay hang ve va chu ky phu tinh theo lich giao va lich nghi cua NCC (vd nghi Tet).
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
    # San muc phuc vu (0 = khong co san). Xem service_floor().
    min_service_level: float = 0.0
    # Suc chua ke/tu: ton sau khi hang ve khong vuot qua (None = khong gioi han)
    max_stock: float | None = None
    # Ton trung bay toi thieu cua hang ben: ton an toan khong thap hon so nay (ke trong mot nua ban kem hon)
    min_display: float = 0.0
    # Ngay hang ve theo lich giao/lich nghi NCC. None = today + lead_time.
    arrival_date: date | None = None


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
    capacity_cap: float | None = None
    capped_by_capacity: bool = False
    service_floor: float = 0.0

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


SERVICE_FLOORS = {"traffic": 0.95, "A": 0.90, "other": 0.50}


def service_floor(is_traffic_driver: bool, abc: str | None, floors: dict | None = None) -> float:
    """San muc phuc vu theo vai tro: hang keo khach >= 95%, nhom A >= 90%, con lai >= 50%."""
    f = floors or SERVICE_FLOORS
    if is_traffic_driver:
        return f["traffic"]
    if abc == "A":
        return f["A"]
    return f["other"]


def compute_order(inp: ReplenishmentInput) -> ReplenishmentResult:
    fc = inp.forecast
    base = inp.first_demand_day or inp.today + timedelta(days=1)

    def demand_at(d: date) -> float:
        return fc.at((d - fc.start).days)

    arrival = inp.arrival_date or inp.today + timedelta(days=max(inp.lead_time_days, 1))
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
    floor = min(max(inp.min_service_level, 0.0), 0.99)
    if perishable:
        sl = max(floor, newsvendor_service_level(inp.unit_cost, inp.unit_price, inp.salvage_per_unit,
                                                 inp.stockout_penalty_per_unit))
        z = NormalDist().inv_cdf(sl)
        mode = "perishable_newsvendor"
    else:
        z = max(inp.z, NormalDist().inv_cdf(floor)) if floor > 0 else inp.z
        sl = NormalDist().cdf(z)
        mode = "order_up_to"
    # Phan phoi lech (mo hinh phan vi): z >= 0 lay do lech phia tren, z < 0 phia duoi; doi xung thi = sigma_daily
    sigma_cov = fc.sigma_for(z) * math.sqrt(R if perishable else L + R)
    safety = z * sigma_cov
    if not perishable:
        safety = max(safety, inp.min_display)
    raw = unmet + safety - leftover

    # 3) Tran HSD: luong lo moi co the ban duoc truoc new_expiry
    window = min(90, max(1, (new_expiry - arrival).days + 1))  # >90 ngay thi tran HSD khong con rang buoc
    demand_window = sum(demand_at(arrival + timedelta(days=k)) for k in range(window))
    lots_win = [list(x) for x in lots]
    served_win, _, _ = _simulate_fefo(lots_win, arrival, window, demand_at)
    z_cap = max(z, 0.0) if perishable else max(z, 1.0)
    cap = max(0.0, demand_window - served_win) + z_cap * fc.sigma_for(z_cap) * math.sqrt(window)
    capped = raw > cap
    qty_f = max(0.0, min(raw, cap))
    cap_room = None
    if inp.max_stock is not None:  # suc chua: ton luc hang ve + so dat <= suc chua
        cap_room = max(0.0, inp.max_stock - usable_at_arrival)
    capped_capacity = cap_room is not None and qty_f > cap_room
    if capped_capacity:
        qty_f = cap_room

    pack = max(1, inp.pack_size)
    if qty_f <= 0:
        qty = 0
    elif perishable:
        qty = int(round(qty_f / pack)) * pack  # lam tron gan nhat de tranh du thua hang tuoi
    else:
        qty = int(math.ceil(qty_f / pack - 1e-9)) * pack
    if cap_room is not None and qty > cap_room:  # khong lam tron vuot suc chua
        qty = int(math.floor(cap_room / pack + 1e-9)) * pack

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
        capacity_cap=cap_room,
        capped_by_capacity=capped_capacity,
        service_floor=floor,
    )


def next_delivery(order_day: date, lead_time_days: int, delivery_weekdays: list[int] | None = None,
                  closed=None) -> date:
    """Ngay hang ve som nhat: sau lead time, roi vao ngay NCC giao hang va khong nam trong ky nghi."""
    d = order_day + timedelta(days=max(lead_time_days, 1))
    for _ in range(90):
        if (not delivery_weekdays or d.weekday() in delivery_weekdays) and not (closed and closed(d)):
            return d
        d += timedelta(days=1)
    return d


def schedule(order_day: date, lead_time_days: int, order_weekdays: list[int], delivery_weekdays: list[int] | None = None,
             closed=None) -> tuple[date, int]:
    """(ngay hang ve cua don hom nay, so ngay can phu = tu luc hang ve den luc don ke tiep ve).

    Don cuoi truoc ky nghi cua NCC tu lon len de phu ca ky nghi (tran HSD van chan)."""
    arrival = next_delivery(order_day, lead_time_days, delivery_weekdays, closed)
    nxt = order_day + timedelta(days=review_period(order_weekdays, order_day))
    for _ in range(90):
        if not (closed and closed(nxt)) and (not order_weekdays or nxt.weekday() in order_weekdays):
            break
        nxt += timedelta(days=1)
    next_arrival = next_delivery(nxt, lead_time_days, delivery_weekdays, closed)
    return arrival, max(1, (next_arrival - arrival).days)


def review_period(order_weekdays: list[int], today: date) -> int:
    """So ngay tu lan dat hom nay toi lan dat ke tiep theo lich NCC."""
    if not order_weekdays:
        return 7
    for k in range(1, 8):
        if (today + timedelta(days=k)).weekday() in order_weekdays:
            return k
    return 7
