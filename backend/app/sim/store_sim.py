"""Cua hang mo phong theo ngay: hang ve -> xu ly can date -> ban FEFO -> huy hang het han -> dat hang."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.engines.kpi import KpiTotals
from app.sim.catalog import ProductSpec, SupplierSpec
from app.sim.demand import _poisson, _rng, expected_demand, sample_demand
from app.sim.world import REFERENCE_WORLD, WorldParams


@dataclass
class SimLot:
    lot_no: int
    sku: str
    qty: int
    expiry: date
    received: date
    unit_cost: int
    markdown: float = 0.0
    evening_md: float = 0.0
    po_code: str | None = None


@dataclass
class SimOrder:
    po_code: str
    supplier: str
    sku: str
    qty: int
    order_date: date
    arrival: date
    unit_cost: int


@dataclass
class PoRecord:
    code: str
    supplier: str
    order_date: date
    arrival: date
    lines: list[tuple[str, int, int]] = field(default_factory=list)  # (sku, qty, unit_cost)


class Policy:
    name = "base"

    def pre_sales(self, sim: "StoreSim", d: date) -> None:  # xu ly hang can date truoc gio ban
        pass

    def evening(self, sim: "StoreSim", d: date) -> None:  # giam gia gio vang tren hang con du
        pass

    def place_orders(self, sim: "StoreSim", d: date) -> None:
        pass


class StoreSim:
    def __init__(self, suppliers: list[SupplierSpec], products: list[ProductSpec], seed: int = 7,
                 record: bool = False, world: WorldParams = REFERENCE_WORLD):
        self.seed = seed
        self.world = world
        self.suppliers = {s.code: s for s in suppliers}
        self.products = products
        self.by_sku = {p.sku: p for p in products}
        self.by_supplier: dict[str, list[ProductSpec]] = defaultdict(list)
        for p in products:
            self.by_supplier[p.supplier_code].append(p)
        self.lots: dict[str, list[SimLot]] = {p.sku: [] for p in products}
        self.pipeline: list[SimOrder] = []
        self.days: list[date] = []
        self.hist: dict[str, dict[str, list]] = {p.sku: defaultdict(list) for p in products}
        self.delisted: set[str] = set()
        self.lot_seq = 0
        self.po_seq = 0
        self.record = record
        self.sales_rows: list[dict] = []
        self.movements: list[dict] = []
        self.pos: dict[str, PoRecord] = {}
        self.totals = KpiTotals(days=0)
        self._inv_sum = 0.0
        self.daily_kpi: list[dict] = []

    # ----- tien ich -----
    def on_hand(self, sku: str) -> int:
        return sum(l.qty for l in self.lots[sku])

    def incoming(self, sku: str) -> list[SimOrder]:
        return [o for o in self.pipeline if o.sku == sku]

    def _mv(self, sku, d, typ, qty, unit_cost, value, ref=None, note=None, reason=None):
        if self.record:
            self.movements.append(dict(sku=sku, date=d, type=typ, qty=int(qty), unit_cost=int(unit_cost),
                                       value=int(round(value)), ref=ref, note=note, reason=reason))

    def add_lot(self, sku: str, qty: int, received: date, unit_cost: int, expiry: date | None = None,
                po_code: str | None = None) -> SimLot:
        p = self.by_sku[sku]
        self.lot_seq += 1
        lot = SimLot(self.lot_seq, sku, int(qty), expiry or received + timedelta(days=p.shelf_life_days - 1),
                     received, unit_cost, po_code=po_code)
        self.lots[sku].append(lot)
        return lot

    def place_order(self, supplier: str, d: date, lines: list[tuple[str, int]]) -> str | None:
        lines = [(s, q) for s, q in lines if q > 0]
        if not lines:
            return None
        sup = self.suppliers[supplier]
        self.po_seq += 1
        code = f"PO{d:%y%m%d}-{supplier[-2:]}{self.po_seq % 1000:03d}"
        arrival = d + timedelta(days=sup.lead_time_days)
        rec = PoRecord(code, supplier, d, arrival)
        for sku, qty in lines:
            cost = int(round(self.by_sku[sku].unit_cost * (1 - sup.discount_pct)))
            self.pipeline.append(SimOrder(code, supplier, sku, int(qty), d, arrival, cost))
            rec.lines.append((sku, int(qty), cost))
            self.totals.purchases_value += qty * cost
        self.pos[code] = rec
        return code

    @staticmethod
    def _sell(p: ProductSpec, lot: SimLot, take: int, md: float, a: list, evening: bool = False) -> None:
        lot.qty -= take
        a[0] += take
        a[1] += take * p.unit_price * (1 - md)
        a[2] += take * lot.unit_cost
        a[3] += take * p.unit_price * md
        if md > 0 and evening:
            a[7] += take
        elif md > 0:
            a[5] += take
            a[6] += take * md

    def apply_markdown(self, lot: SimLot, pct: float, d: date, evening: bool = False) -> None:
        if evening:
            lot.evening_md = max(lot.evening_md, pct)
        elif pct > lot.markdown:
            lot.markdown = pct

    def apply_return(self, lot: SimLot, units: int, credit_pct: float, d: date) -> None:
        units = min(units, lot.qty)
        if units <= 0:
            return
        lot.qty -= units
        credit = units * lot.unit_cost * credit_pct
        self.totals.return_credit += credit
        self.totals.return_cost += units * lot.unit_cost
        self._mv(lot.sku, d, "RETURN", units, lot.unit_cost, credit, note=f"Trả NCC, hoàn {credit_pct:.0%}")

    def _non_fefo_units(self, sku: str, d: date, need: int) -> int:
        """So don vi khach lay tu lo moi nhat thay vi lo gan het han."""
        c = self.world.fefo_compliance
        if c >= 1 or need <= 0:
            return 0
        r = _rng(self.seed, "pick", sku, d.toordinal())
        return sum(1 for _ in range(need) if r.random() > c)

    # ----- mot ngay -----
    def run_day(self, d: date, policy: Policy) -> None:
        self.days.append(d)
        t = self.totals
        t.days += 1
        day = dict(date=d, revenue=0.0, cogs=0.0, waste_cost=0.0, lost=0, sold=0, inv_value=0.0)

        arrived = [o for o in self.pipeline if o.arrival <= d]
        self.pipeline = [o for o in self.pipeline if o.arrival > d]
        for o in arrived:
            self.add_lot(o.sku, o.qty, d, o.unit_cost, po_code=o.po_code)
            self._mv(o.sku, d, "IN", o.qty, o.unit_cost, o.qty * o.unit_cost, ref=o.po_code)

        policy.pre_sales(self, d)

        acc: dict[str, list] = {}  # sku -> [sold, rev, cogs, md_loss, lost]
        for p in self.products:
            sku = p.sku
            lots = self.lots[sku]
            lots.sort(key=lambda l: (l.expiry, l.lot_no))
            need = sample_demand(self.seed, p, d)
            # sold, rev, cogs, md_loss, lost, so ban giam gia ca ngay, tong (so x muc giam), so ban gio vang
            a = acc[sku] = [0, 0.0, 0.0, 0.0, 0, 0, 0.0, 0]
            from_back = self._non_fefo_units(sku, d, need)
            need -= from_back
            for order, units in ((lots, need), (lots[::-1], from_back)):  # ban theo FEFO, roi khach lay lo moi
                for lot in order:
                    if units <= 0:
                        break
                    take = min(lot.qty, units)
                    if take > 0:
                        self._sell(p, lot, take, lot.markdown, a)
                        units -= take
                a[4] += units
            md_lots = [l for l in lots if l.markdown > 0 and l.qty > 0]
            if md_lots:
                top = max(l.markdown for l in md_lots)
                lam = expected_demand(self.seed, p, d) * self.world.elasticity[p.freshness_class] * top
                extra = _poisson(_rng(self.seed, "md", sku, d.toordinal()), lam)
                for lot in md_lots:
                    take = min(lot.qty, extra)
                    if take > 0:
                        self._sell(p, lot, take, lot.markdown, a)
                        extra -= take

        # Chieu toi: quyet dinh giam gia gio vang dua tren luong hang THUC TE con du
        policy.evening(self, d)
        for p in self.products:
            sku = p.sku
            a = acc[sku]
            ev_lots = [l for l in self.lots[sku] if l.evening_md > 0 and l.qty > 0 and l.expiry <= d]
            if ev_lots:
                top = max(l.evening_md for l in ev_lots)
                # Vong ban o tren da tinh ca ngay gia goc; khach toi trong so do cung duoc huong gia giam
                rebate = min(self.world.evening_share * (a[0] - a[5]), sum(l.qty for l in ev_lots)) * p.unit_price * top
                a[1] -= rebate
                a[3] += rebate
                lam = (expected_demand(self.seed, p, d) * self.world.evening_share
                       * self.world.elasticity[p.freshness_class] * top)
                extra = _poisson(_rng(self.seed, "ev", sku, d.toordinal()), lam)
                for lot in ev_lots:
                    take = min(lot.qty, extra)
                    if take > 0:
                        self._sell(p, lot, take, lot.evening_md, a, evening=True)
                        extra -= take
            sold, rev, cogs, md_loss, lost, md_units, md_weighted, ev_units = a
            if md_loss:
                self._mv(sku, d, "MARKDOWN", 0, 0, md_loss, note="Doanh thu giảm do giảm giá")
            self.lots[sku] = [l for l in self.lots[sku] if l.qty > 0]

            h = self.hist[sku]
            h["sales"].append(sold)
            h["md_units"].append(md_units)
            h["md_pct"].append(md_weighted / md_units if md_units else 0.0)
            h["ev_units"].append(ev_units)
            h["stockout"].append(lost > 0)
            h["lost"].append(lost)
            h["revenue"].append(rev)
            h["cogs"].append(cogs)
            t.revenue += rev
            t.cogs += cogs
            t.units_sold += sold
            t.units_lost += lost
            t.lost_margin += lost * (p.unit_price - p.unit_cost)
            t.markdown_loss += md_loss
            day["revenue"] += rev
            day["cogs"] += cogs
            day["sold"] += sold
            day["lost"] += lost
            if self.record and (sold or lost):
                self.sales_rows.append(dict(sku=sku, date=d, qty_sold=sold, revenue=int(round(rev)),
                                            cogs=int(round(cogs)), lost_qty=lost, stockout=lost > 0))

        for p in self.products:
            sku = p.sku
            waste_cost = 0.0
            keep = []
            for lot in self.lots[sku]:
                if lot.expiry <= d and lot.qty > 0:
                    waste_cost += lot.qty * lot.unit_cost
                    t.waste_units += lot.qty
                    self._mv(sku, d, "WASTE", lot.qty, lot.unit_cost, lot.qty * lot.unit_cost,
                             note="Hết hạn sử dụng", reason="EXPIRED")
                else:
                    keep.append(lot)
            self.lots[sku] = keep
            self.hist[sku]["waste_cost"].append(waste_cost)
            t.waste_cost += waste_cost
            day["waste_cost"] += waste_cost
            day["inv_value"] += sum(l.qty * l.unit_cost for l in keep)

        self._inv_sum += day["inv_value"]
        t.avg_inventory_value = self._inv_sum / t.days
        self.daily_kpi.append(day)

        policy.place_orders(self, d)

    def run(self, start: date, days: int, policy: Policy) -> None:
        for k in range(days):
            self.run_day(start + timedelta(days=k), policy)

    def reset_totals(self) -> None:
        self.totals = KpiTotals(days=0)
        self._inv_sum = 0.0
        self.daily_kpi = []
