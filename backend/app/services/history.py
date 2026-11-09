"""Nap lich su ban/huy tu DB thanh chuoi theo ngay cho engine. Co cache theo phien ban du lieu."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import today
from app.engines.abc_xyz import SkuClass, SkuStats, classify
from app.engines.disposition import ELASTICITY
from app.engines.forecast import Forecast, baseline_demand, estimate_event_factors, forecast_demand
from app.models import DailySales, DemandHypothesis, Product, StockMovement


@dataclass
class History:
    end: date  # ngay cuoi co du lieu (hom qua)
    days: int
    sales: dict[int, list[float]]
    stockout: dict[int, list[bool]]
    revenue: dict[int, list[float]]
    cogs: dict[int, list[float]]
    waste_cost: dict[int, list[float]]
    demand: dict[int, list[float]]  # luong ban da bo phan nho giam gia: dau vao cua du bao

    def series(self, pid: int, name: str, last: int | None = None) -> list:
        s = getattr(self, name).get(pid)
        if s is None:
            s = [False if name == "stockout" else 0.0] * self.days
        return s[-last:] if last else s


_cache: dict = {}


def _version(db: Session) -> tuple:
    return (
        db.scalar(select(func.count()).select_from(DailySales)),
        db.scalar(select(func.max(StockMovement.id))),
    )


def load_history(db: Session, days: int = 400) -> History:
    end = today() - timedelta(days=1)
    key = ("hist", end, days, _version(db))
    if key in _cache:
        return _cache[key]
    start = end - timedelta(days=days - 1)
    freshness = dict(db.execute(select(Product.id, Product.freshness_class)).all())
    pids = list(freshness)
    mk = lambda v: {pid: [v] * days for pid in pids}  # noqa: E731
    h = History(end, days, mk(0.0), mk(False), mk(0.0), mk(0.0), mk(0.0), mk(0.0))
    rows = db.execute(
        select(DailySales.product_id, DailySales.date, DailySales.qty_sold, DailySales.revenue,
               DailySales.cogs, DailySales.stockout, DailySales.discounted_qty, DailySales.discount_pct,
               DailySales.evening_qty)
        .where(DailySales.date >= start, DailySales.date <= end)
    ).all()
    for pid, d, q, rev, cogs, so, disc, pct, ev in rows:
        i = (d - start).days
        h.sales[pid][i] = float(q)
        h.demand[pid][i] = baseline_demand(float(q), float(disc or 0), float(pct or 0), float(ev or 0),
                                           ELASTICITY[freshness[pid]])
        h.revenue[pid][i] = float(rev)
        h.cogs[pid][i] = float(cogs)
        h.stockout[pid][i] = bool(so)
    wrows = db.execute(
        select(StockMovement.product_id, StockMovement.date, func.sum(StockMovement.value))
        .where(StockMovement.type == "WASTE", StockMovement.date >= start, StockMovement.date <= end)
        .group_by(StockMovement.product_id, StockMovement.date)
    ).all()
    for pid, d, v in wrows:
        h.waste_cost[pid][(d - start).days] = float(v or 0)
    _cache.clear()
    _cache[key] = h
    return h


_event_cache: dict = {}


def event_factors(h: History, pid: int) -> dict:
    key = (h.end, pid)
    if key not in _event_cache:
        _event_cache[key] = estimate_event_factors(h.demand[pid], h.end) if h.days >= 120 else {}
    return _event_cache[key]


def hypotheses_for(db: Session, product: Product) -> list[DemandHypothesis]:
    rows = db.scalars(select(DemandHypothesis).where(DemandHypothesis.status != "CANCELLED")).all()
    return [x for x in rows if x.sku == product.sku or (x.category is not None and x.category == product.category)]


def _apply_hypotheses(fc: Forecast, active: list[DemandHypothesis]) -> None:
    applied: dict[int, float] = {}
    for k in range(len(fc.daily)):
        d = fc.start + timedelta(days=k)
        for x in active:
            if x.start_date <= d <= x.end_date:
                fc.daily[k] *= x.factor
                applied[x.id] = x.factor
    fc.adjustments = [{"hypothesis_id": i, "factor": f} for i, f in applied.items()]


def forecast_for(db: Session, product: Product, horizon: int = 14, start: date | None = None,
                 with_hypotheses: bool = True) -> Forecast:
    h = load_history(db)
    hyps = hypotheses_for(db, product)
    skip = {x.start_date + timedelta(days=i) for x in hyps for i in range((x.end_date - x.start_date).days + 1)}
    fc = forecast_demand(
        h.series(product.id, "demand", 120), h.end, horizon,
        stockout=h.series(product.id, "stockout", 120),
        start=start or today(), event_factors=event_factors(h, product.id), skip_dates=skip,
    )
    if with_hypotheses:
        _apply_hypotheses(fc, [x for x in hyps if x.status == "ACTIVE"])
    return fc


def sku_stats(db: Session, window: int = 90) -> tuple[list[SkuStats], dict[str, Product]]:
    h = load_history(db)
    products = db.scalars(select(Product)).all()
    by_sku = {p.sku: p for p in products}
    stats = []
    for p in products:
        sales = h.series(p.id, "demand", window)
        weekly = [sum(sales[i:i + 7]) for i in range(len(sales) % 7, len(sales), 7)]
        rev = sum(h.series(p.id, "revenue", window))
        cogs = sum(h.series(p.id, "cogs", window))
        waste = sum(h.series(p.id, "waste_cost", window))
        stats.append(SkuStats(
            sku=p.sku, name=p.name, gross_margin_after_waste=rev - cogs - waste, weekly_demand=weekly,
            waste_rate=waste / (cogs + waste) if (cogs + waste) else 0.0,
            is_traffic_driver=p.is_traffic_driver,
            substitutes=[s for s in (p.substitute_skus or []) if by_sku.get(s) and by_sku[s].status == "ACTIVE"],
        ))
    return stats, by_sku


def abc_xyz_classes(db: Session) -> dict[str, SkuClass]:
    h = load_history(db)
    key = ("abc", h.end, _version(db))
    if key not in _cache:
        stats, _ = sku_stats(db)
        _cache[key] = classify(stats)
    return _cache[key]


def daily_totals(db: Session, start: date, end: date) -> dict[date, dict]:
    """Tong hop theo ngay toan cua hang (dung cho KPI, bieu do)."""
    out: dict[date, dict] = defaultdict(lambda: defaultdict(float))
    for d, q, rev, cogs, lost in db.execute(
        select(DailySales.date, func.sum(DailySales.qty_sold), func.sum(DailySales.revenue),
               func.sum(DailySales.cogs), func.sum(DailySales.lost_qty))
        .where(DailySales.date >= start, DailySales.date <= end).group_by(DailySales.date)
    ):
        o = out[d]
        o["sold"], o["revenue"], o["cogs"], o["lost"] = float(q or 0), float(rev or 0), float(cogs or 0), float(lost or 0)
    for d, typ, q, v in db.execute(
        select(StockMovement.date, StockMovement.type, func.sum(StockMovement.qty), func.sum(StockMovement.value))
        .where(StockMovement.date >= start, StockMovement.date <= end)
        .group_by(StockMovement.date, StockMovement.type)
    ):
        o = out[d]
        o[f"{typ.lower()}_qty"] = float(q or 0)
        o[f"{typ.lower()}_value"] = float(v or 0)
    return out
