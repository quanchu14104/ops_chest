"""Tua nhanh ngay cho demo: mo phong hang ve + ban hang len DB that de thay hau qua cua quyet dinh.

Cac buoc thuoc ve Store Manager van KHONG tu xay ra: khong duyet de xuat, khong dat hang, khong ghi huy.
Bo qua duyet thi ke se trong dan va lo da rut ke nam cho ghi huy: do chinh la dieu can cho thay. Viec cua
nhan vien (nhan hang voi HSD chuan, rut ke cuoi ngay dung so tren so) duoc gia lap voi actor `sim`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, clock
from app.jobs.daily import run_morning
from app.models import AppMeta, DailySales, Lot, Product, PurchaseOrder, StockMovement
from app.proposals import service
from app.services import hypotheses, policies, snapshots
from app.services.inventory import active_lots
from app.services.receiving import default_expiry, receive_po
from app.services.shelf import confirm_pull, pull_list
from app.sim.catalog import build_catalog
from app.sim.demand import DemandSource, FrnDemand, FrnRangeError, SyntheticDemand, _poisson, _rng
from app.sim.world import REFERENCE_WORLD, WorldParams

MAX_DAYS = 14
SEED = 7


@dataclass
class _SimStaff:
    username: str = "sim"


def _receive_arrivals(db: Session, d: date) -> int:
    pos = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "SENT", PurchaseOrder.expected_date <= d)).all()
    for po in pos:
        receive_po(db, po.id, [{"line_id": l.id, "received_qty": l.qty,
                                "expiry_date": default_expiry(l.product.shelf_life_days, d).isoformat()}
                               for l in po.lines], _SimStaff())
    return len(pos)


def _true_multiplier(product: Product, active: list, d: date) -> float:
    f = 1.0
    for x in active:
        if x.start_date <= d <= x.end_date and (x.sku == product.sku or x.category == product.category):
            f *= x.factor
    return f


def _sell(lot: Lot, take: int, price: int, pct: float, a: dict) -> None:
    lot.qty_remaining -= take
    if lot.qty_remaining == 0:
        lot.status = "SOLD"
    a["sold"] += take
    a["revenue"] += take * price * (1 - pct)
    a["cogs"] += take * lot.unit_cost
    a["md_loss"] += take * price * pct


def simulate_day(db: Session, d: date, specs: dict, realize_hypotheses: bool, source: DemandSource | None = None,
                 world: WorldParams = REFERENCE_WORLD) -> dict:
    source = source or SyntheticDemand(SEED)
    received = _receive_arrivals(db, d)
    products = db.scalars(select(Product)).all()
    lots_by_pid = active_lots(db, [p.id for p in products])
    active = list(db.scalars(select(hypotheses.DemandHypothesis).where(hypotheses.DemandHypothesis.status == "ACTIVE")))
    pol = policies.by_category(db)
    day = {"date": d.isoformat(), "received_pos": received, "revenue": 0.0, "sold": 0, "lost": 0, "stockout_skus": 0}
    for p in products:
        spec = specs.get(p.sku)
        if spec is None or db.get(DailySales, (p.id, d)):
            continue
        need = source.need(spec, d)
        if realize_hypotheses:
            need = int(round(need * _true_multiplier(p, active, d)))
        lots = sorted((l for l in lots_by_pid.get(p.id, []) if l.sell_by >= d), key=lambda l: (l.expiry_date, l.id))
        a = {"sold": 0, "revenue": 0.0, "cogs": 0.0, "md_loss": 0.0, "discounted": 0, "weighted": 0.0, "evening": 0}

        def all_day_pct(l: Lot) -> float:
            return l.markdown_pct if l.sell_by > d else 0.0

        for lot in lots:
            take = min(lot.qty_remaining, need)
            if take <= 0:
                continue
            pct = all_day_pct(lot)
            _sell(lot, take, p.unit_price, pct, a)
            need -= take
            if pct > 0:
                a["discounted"] += take
                a["weighted"] += take * pct
        lost = need
        expected = source.expected(spec, d)
        marked = [l for l in lots if all_day_pct(l) > 0 and l.qty_remaining > 0]
        if marked:
            top = max(l.markdown_pct for l in marked)
            extra = _poisson(_rng(SEED, "md", p.sku, d.toordinal()),
                             expected * world.elasticity[p.freshness_class] * top)
            for lot in marked:
                take = min(lot.qty_remaining, extra)
                if take > 0:
                    _sell(lot, take, p.unit_price, lot.markdown_pct, a)
                    a["discounted"] += take
                    a["weighted"] += take * lot.markdown_pct
                    extra -= take
        evening = [l for l in lots if l.sell_by == d and l.markdown_pct > 0 and l.qty_remaining > 0]
        if evening:
            top = max(l.markdown_pct for l in evening)
            share = world.share_after(p.category, policies.for_category(pol, p.category)["markdown_hour"])
            rebate = (min(share * (a["sold"] - a["discounted"]), sum(l.qty_remaining for l in evening))
                      * p.unit_price * top)  # khach sau gio giam gia von tra gia goc cung duoc huong gia giam
            a["revenue"] -= rebate
            a["md_loss"] += rebate
            extra = _poisson(_rng(SEED, "ev", p.sku, d.toordinal()),
                             expected * share * world.elasticity[p.freshness_class] * top)
            for lot in evening:
                take = min(lot.qty_remaining, extra)
                if take > 0:
                    _sell(lot, take, p.unit_price, lot.markdown_pct, a)
                    a["evening"] += take
                    extra -= take
        if a["sold"] or lost:
            db.add(DailySales(product_id=p.id, date=d, qty_sold=a["sold"], revenue=int(round(a["revenue"])),
                              cogs=int(round(a["cogs"])), lost_qty=lost, stockout=lost > 0,
                              discounted_qty=a["discounted"], discount_pct=a["weighted"] / a["discounted"] if a["discounted"] else 0.0,
                              evening_qty=a["evening"]))
        if a["md_loss"]:
            db.add(StockMovement(product_id=p.id, date=d, type="MARKDOWN", qty=0, unit_cost=0,
                                 value=int(round(a["md_loss"])), note="Doanh thu giảm do giảm giá"))
        day["revenue"] += a["revenue"]
        day["sold"] += a["sold"]
        day["lost"] += lost
        day["stockout_skus"] += lost > 0
    day["revenue"] = int(round(day["revenue"]))
    # Cuoi ngay nhan vien rut ke cac lo het ngay ban (gia lap: tim thay dung so tren so)
    due = pull_list(db, d)
    if due:
        by_id = {l.id: l for ls in lots_by_pid.values() for l in ls}
        confirm_pull(db, [{"lot_id": x["lot_id"], "pulled_qty": by_id[x["lot_id"]].qty_remaining if x["lot_id"] in by_id
                           else db.get(Lot, x["lot_id"]).qty_remaining} for x in due], "sim")
    day["pulled_lots"] = len(due)
    snapshots.record(db, d)
    db.commit()
    return day


def demand_setup(db: Session) -> tuple[dict, DemandSource, WorldParams]:
    """Nguon nhu cau theo du lieu da seed: FRN (nhu cau that cua diem ban da chon) hoac the gioi gia lap cu."""
    row = db.get(AppMeta, "data_source")
    if row and row.value == "frn":
        from app.sim import frn
        from app.sim.frn_catalog import build_frn_catalog
        from app.sim.world import frn_world

        sid = db.get(AppMeta, "frn_store")
        store = frn.store(int(sid.value) if sid else None)
        k = frn.k_scale()
        _, spec_list = build_frn_catalog(store, k)
        return {s.sku: s for s in spec_list}, FrnDemand(store, k), frn_world(store.store_id)
    _, spec_list = build_catalog()
    return {s.sku: s for s in spec_list}, SyntheticDemand(SEED), REFERENCE_WORLD


def set_clock(db: Session, d: date) -> None:
    clock.set_today(d)
    db.merge(AppMeta(key=clock.SIM_CLOCK_KEY, value=d.isoformat()))
    db.commit()


def advance(db: Session, days: int, actor: str, realize_hypotheses: bool = True) -> dict:
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"Chỉ tua được 1–{MAX_DAYS} ngày một lần.")
    specs, source, world = demand_setup(db)
    start = clock.today()
    if isinstance(source, FrnDemand):
        last = source.store.dates[-1]
        if start + timedelta(days=days - 1) > last:
            left = (last - start).days + 1
            raise FrnRangeError(f"Hết dữ liệu FRN sau {last.strftime('%d/%m/%Y')}: chỉ còn tua được {max(0, left)} ngày.")
    log, expired, evaluated = [], 0, []
    for k in range(days):
        d = start + timedelta(days=k)
        log.append(simulate_day(db, d, specs, realize_hypotheses, source, world))
        set_clock(db, d + timedelta(days=1))
        expired += service.expire_stale(db)
        evaluated += hypotheses.evaluate_finished(db)
        db.commit()
    morning = run_morning(db)
    new_today = clock.today()
    stale = db.scalars(select(Lot).where(Lot.status == "PULLED")).all()
    out = {
        "from": start.isoformat(), "to": new_today.isoformat(), "days": log, "proposals_expired_unanswered": expired,
        "hypotheses_evaluated": evaluated + morning["hypotheses_evaluated"], "new_proposals": morning["proposals"],
        "totals": {"revenue": sum(x["revenue"] for x in log), "sold": sum(x["sold"] for x in log),
                   "lost": sum(x["lost"] for x in log), "received_pos": sum(x["received_pos"] for x in log)},
        "pulled_awaiting_writeoff_value": sum(l.qty_remaining * l.unit_cost for l in stale),
    }
    audit.log(db, actor, "SIM_ADVANCED", "clock", new_today.isoformat(),
              {"from": start.isoformat(), "days": days, "realize_hypotheses": realize_hypotheses})
    db.commit()
    return out
