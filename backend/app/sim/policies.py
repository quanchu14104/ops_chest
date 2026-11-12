"""Hai chinh sach dat hang de so sanh trong backtest.

A - BaselinePolicy ("kinh nghiem"): muc ton muc tieu = TB ban 28 ngay x so ngay can phu x he so an toan.
    Khong biet thu trong tuan, Tet, het hang lam doanh so thap, khong xu ly hang can date.
A' - BaselineGoldenHourPolicy: A + giam 30% buoi toi hang het han hom nay, dung nhu chu tiem binh thuong.
    Day la doi thu so sanh mac dinh; so voi A thuan thi phan loi cua giam gia bi tinh het cho B.
B - OpsChestPolicy: dung dung cac engine cua Ops Chest (du bao, newsvendor/order-up-to, tran HSD,
    ABC-XYZ, de xuat giam gia/tra hang). Trong mo phong coi nhu SM duyet het de xuat.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from app.engines.abc_xyz import Z_BY_CLASS, SkuStats, classify
from app.engines.disposition import ELASTICITY, EVENING_SHARE, DispositionInput, best
from app.engines.expiry import LotInput, project_lots
from app.engines.forecast import baseline_demand, estimate_event_factors
from app.engines.forecast_router import forecast as route_forecast
from app.sim.frn import holiday_of as frn_holiday_of
from app.config import service_floors
from app.engines.replenishment import (Incoming, LotState, ReplenishmentInput, compute_order, review_period, schedule,
                                       service_floor)
from app.sim.catalog import ProductSpec, category_policy
from app.sim.demand import _rng
from app.sim.store_sim import Policy, StoreSim, can_order

AT_RISK_DAYS = {"FRESH": 1, "SHORT": 3, "LONG": 45}


def salvage_value(p: ProductSpec, accepts_return: bool, credit_pct: float) -> float:
    """Tien thu hoi ky vong cho 1 don vi khong ban duoc gia goc (giam gia cuoi ngay hoac tra NCC)."""
    v = 0.2 * p.unit_price if p.freshness_class in ("FRESH", "SHORT") else 0.0
    if accepts_return:
        v = max(v, 0.5 * p.unit_cost * credit_pct)
    return v


class BaselinePolicy(Policy):
    name = "A: Kinh nghiệm (par level)"

    def __init__(self, safety: float = 1.2):
        self.safety = safety

    def place_orders(self, sim: StoreSim, d: date) -> None:
        for code, sup in sim.suppliers.items():
            if can_order(sup, d):  # baseline khong tinh truoc ky nghi: dat nhu tuan thuong
                self.order_supplier(sim, d, code, sup)

    def order_supplier(self, sim: StoreSim, d: date, code: str, sup) -> None:
        R = review_period(sup.order_weekdays, d)
        L = sup.lead_time_days
        lines = []
        for p in sim.by_supplier[code]:
            if p.sku in sim.delisted:
                continue
            sales = sim.hist[p.sku]["sales"][-28:]
            m = sum(sales) / len(sales) if len(sales) >= 7 else p.base_rate
            if p.shelf_life_days <= R + 7:
                # "ngay ban tot": TB + 1 do lech chuan doanh so 4 tuan qua
                sd = (sum((x - m) ** 2 for x in sales) / max(1, len(sales) - 1)) ** 0.5 if len(sales) > 1 else 0
                target = m * R * 1.15 + 0.5 * sd
            else:
                target = m * (L + R) * self.safety + m
            position = sim.on_hand(p.sku) + sum(o.qty for o in sim.incoming(p.sku))
            q = target - position
            if q > 0.5:
                lines.append((p.sku, int(math.ceil(q / p.pack_size)) * p.pack_size))
        sim.place_order(code, d, lines)


class BaselineGoldenHourPolicy(BaselinePolicy):
    name = "A: Kinh nghiệm + giờ vàng 30%"

    def evening(self, sim: StoreSim, d: date) -> None:
        for lots in sim.lots.values():
            for lot in lots:
                if lot.expiry <= d and lot.qty > 0:
                    sim.apply_markdown(lot, 0.3, d, evening=True)


class OpsChestPolicy(Policy):
    name = "B: Ops Chest"

    def __init__(self, dispose: bool = True, lookback_classify: int = 90, adjust_markdown: bool = True,
                 approval_rate: float = 1.0, service_floors: bool = True, floors: dict | None = None,
                 dayparts: bool = True, ml_model: str | None = None, gate: dict | None = None):
        self.dispose = dispose
        # Du bao: None = engine EWMA; "" / "bt_" = bo chon LightGBM/EWMA voi mo hinh chay that / mo hinh backtest
        # (mo hinh backtest chi thay du lieu truoc ky so sanh). Chi ap cho mat hang co nhu cau FRN.
        self.ml_model = ml_model
        # Bo chon tam (backtest truyen vao, khong doc decision_gate.json): nhom dung ML va bien the sigma
        # (sym / split / ewma_sigma). None = de forecaster tu doc file / meta.json.
        self.gate = gate
        # San muc phuc vu theo vai tro (N6). Tat = cach cu: newsvendor co the de thieu hang toi 70% so ngay.
        self.service_floors = service_floors
        self.floors = floors  # None = lay theo config (SERVICE_FLOOR_*)
        # Gio giam gia theo khung ban cua nhom hang (N10). Tat = gio vang co dinh 18h, 30% khach cho moi nhom.
        self.dayparts = dayparts
        self.lookback = lookback_classify
        self.adjust_markdown = adjust_markdown  # tach luong ban nho giam gia khoi nhu cau khi du bao
        # Ty le de xuat duoc SM duyet. Don khong duoc duyet thi SM tu dat theo kinh nghiem; giam gia thi bo qua.
        self.approval_rate = approval_rate
        self._habit = BaselinePolicy()
        self.classes: dict[str, str] = {}
        self._last_classify: date | None = None
        self._events: dict[str, dict] = {}
        self._events_at: date | None = None
        self.actions = {"markdown": 0, "return": 0}

    # --- tien ich ---
    def _approved(self, sim: StoreSim, *key, d: date) -> bool:
        return self.approval_rate >= 1 or _rng(sim.seed, "approve", *key, d.toordinal()).random() < self.approval_rate

    def _demand(self, sim: StoreSim, p: ProductSpec, last: int) -> list[float]:
        """Chuoi nhu cau cho du bao, chi dung thu cua hang quan sat duoc (khong nhin so that cua gia lap)."""
        h = sim.hist[p.sku]
        sales = h["sales"][-last:]
        if not self.adjust_markdown:
            return sales
        e = ELASTICITY[p.freshness_class]
        return [baseline_demand(s, m, pct, ev, e) for s, m, pct, ev in
                zip(sales, h["md_units"][-last:], h["md_pct"][-last:], h["ev_units"][-last:])]

    def _event_factors(self, sim: StoreSim, d: date) -> dict[str, dict]:
        if self._events_at is None or (d - self._events_at).days >= 30:
            self._events = {p.sku: estimate_event_factors(self._demand(sim, p, 400), d - timedelta(days=1))
                            if len(sim.hist[p.sku]["sales"]) >= 120 else {} for p in sim.products}
            self._events_at = d
        return self._events

    def _classify(self, sim: StoreSim, d: date) -> None:
        if self._last_classify and (d - self._last_classify).days < 7:
            return
        n = self.lookback
        stats = []
        for p in sim.products:
            h = sim.hist[p.sku]
            sales = self._demand(sim, p, n)
            if not sales:
                continue
            margin = sum(h["revenue"][-n:]) - sum(h["cogs"][-n:]) - sum(h["waste_cost"][-n:])
            weekly = [sum(sales[i:i + 7]) for i in range(len(sales) % 7, len(sales), 7)]
            stats.append(SkuStats(p.sku, p.name, margin, weekly))
        if stats:
            self.classes = {k: v.cell for k, v in classify(stats).items()}
        self._last_classify = d

    def _forecast(self, sim: StoreSim, p: ProductSpec, end: date, horizon: int, start: date | None = None):
        h = sim.hist[p.sku]
        events = self._event_factors(sim, end + timedelta(days=1)).get(p.sku, {})
        statics = None
        store = getattr(sim.demand, "store", None)
        if self.ml_model is not None and p.frn_id is not None and store is not None:
            x = store.series[p.frn_id]
            statics = (x.management_group_id, x.first_category_id, x.second_category_id)
        return route_forecast(self._demand(sim, p, 120), end, horizon, stockout=h["stockout"][-120:], start=start,
                              event_factors=events, frn_statics=statics, model=self.ml_model or "",
                              holiday_of=frn_holiday_of(store) if store is not None else None,
                              store_size=len(store.series) if store is not None else None, gate=self.gate)

    # --- xu ly can date (sang som, truoc khi ban) ---
    def pre_sales(self, sim: StoreSim, d: date) -> None:
        if not self.dispose or not sim.days or len(sim.days) < 2:
            return
        for p in sim.products:
            lots = sim.lots[p.sku]
            thr = AT_RISK_DAYS[p.freshness_class]
            at_risk = [l for l in lots if 1 <= (l.expiry - d).days <= max(thr, 1) and l.qty > 0]
            if not at_risk:
                continue
            horizon = max((l.expiry - d).days for l in lots) + 1
            fc = self._forecast(sim, p, d - timedelta(days=1), min(horizon, 120), start=d)
            risks = {r.lot_id: r for r in project_lots(
                [LotInput(l.lot_no, l.qty, l.expiry) for l in lots], fc.daily, d)}
            sup = sim.suppliers[p.supplier_code]
            for lot in at_risk:
                r = risks.get(lot.lot_no)
                if not r or r.expected_waste < 1 or not self._approved(sim, "lot", lot.lot_no, d=d):
                    continue
                opt = best(DispositionInput(
                    qty=lot.qty, unit_cost=lot.unit_cost, unit_price=p.unit_price, days_left=r.days_left,
                    expected_sold_full_price=r.expected_sold, elasticity=ELASTICITY[p.freshness_class],
                    accepts_return=sup.accepts_return, return_min_days_before_expiry=sup.return_min_days,
                    return_credit_pct=sup.return_credit_pct, daily_demand=fc.daily[0], current_markdown=lot.markdown,
                ))
                if opt.action == "MARKDOWN":
                    sim.apply_markdown(lot, opt.markdown_pct, d, evening=opt.timing == "EVENING")
                    self.actions["markdown"] += 1
                elif opt.action == "RETURN":
                    sim.apply_return(lot, int(round(opt.units_returned)), sup.return_credit_pct, d)
                    self.actions["return"] += 1

    # --- gio vang: hang het han hom nay con du sau gio ban chinh ---
    def evening(self, sim: StoreSim, d: date) -> None:
        if not self.dispose:
            return
        for p in sim.products:
            left = [l for l in sim.lots[p.sku] if l.expiry <= d and l.qty > 0]
            if not left:
                continue
            fc_today = self._forecast(sim, p, d - timedelta(days=1), 1, start=d).daily[0]
            pol = category_policy(p.category)
            share, hour = (pol["remaining_share"], pol["markdown_hour"]) if self.dayparts else (EVENING_SHARE, 18)
            for lot in left:
                if not self._approved(sim, "evening", lot.lot_no, d=d):
                    continue
                opt = best(DispositionInput(
                    qty=lot.qty, unit_cost=lot.unit_cost, unit_price=p.unit_price, days_left=0,
                    expected_sold_full_price=0, elasticity=ELASTICITY[p.freshness_class],
                    daily_demand=fc_today, current_markdown=lot.markdown,
                    evening_full_price_units=fc_today * share, remaining_share=share, markdown_hour=hour,
                    max_markdown=pol["max_markdown_pct"], markdown_allowed=pol["markdown_allowed"],
                ))
                if opt.action == "MARKDOWN":
                    sim.apply_markdown(lot, opt.markdown_pct, d, evening=True, hour=hour)
                    self.actions["markdown"] += 1
                elif lot.markdown > 0:  # lo da dan tem giam tu truoc: cuoi ngay van ban o muc do
                    sim.apply_markdown(lot, lot.markdown, d, evening=True, hour=hour)

    # --- dat hang (cuoi ngay) ---
    def place_orders(self, sim: StoreSim, d: date) -> None:
        self._classify(sim, d)
        floors = self.floors or service_floors()
        for code, sup in sim.suppliers.items():
            if not can_order(sup, d):
                continue
            if not self._approved(sim, "po", code, d=d):
                self._habit.order_supplier(sim, d, code, sup)
                continue
            arrival, R = schedule(d, sup.lead_time_days, sup.order_weekdays, sup.delivery_weekdays, sup.is_closed)
            L = sup.lead_time_days
            lead = (arrival - d).days
            lines = []
            for p in sim.by_supplier[code]:
                if p.sku in sim.delisted:
                    continue
                cell = self.classes.get(p.sku, "BY")
                inp = build_input(
                    p, d, L, R, self._forecast(sim, p, d, lead + R + min(p.shelf_life_days, 30) + 2),
                    [LotState(l.qty, l.expiry) for l in sim.lots[p.sku]],
                    [Incoming(o.qty, o.arrival, o.arrival + timedelta(days=p.shelf_life_days - 1))
                     for o in sim.incoming(p.sku)],
                    Z_BY_CLASS.get(cell, 1.28),
                    salvage_value(p, sup.accepts_return, sup.return_credit_pct),
                )
                inp.arrival_date = arrival
                inp.max_stock = p.max_stock_qty
                inp.min_display = p.min_display_qty
                if self.service_floors:
                    inp.min_service_level = service_floor(p.is_traffic_driver, cell[0], floors)
                res = compute_order(inp)
                if res.qty > 0:
                    lines.append((p.sku, res.qty))
            sim.place_order(code, d, lines)


def stockout_penalty(p) -> float:
    """Chi phi co hoi/mat khach moi don vi het hang: 30% gia ban, 100% voi hang keo khach."""
    return p.unit_price * (1.0 if p.is_traffic_driver else 0.3)


def build_input(p, today, L, R, fc, lots, incoming, z, salvage) -> ReplenishmentInput:
    return ReplenishmentInput(
        today=today, lead_time_days=L, review_period_days=R, shelf_life_days=p.shelf_life_days,
        forecast=fc, lots=lots, incoming=incoming, pack_size=p.pack_size, z=z,
        unit_cost=p.unit_cost, unit_price=p.unit_price, salvage_per_unit=salvage,
        stockout_penalty_per_unit=stockout_penalty(p),
    )
