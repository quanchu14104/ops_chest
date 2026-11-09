"""Gia thuyet nhu cau cua Store Manager: xem truoc tac dong, cham dung/sai sau khi su kien qua di."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app import audit
from app.clock import today
from app.engines.forecast import hypothesis_verdict
from app.models import DailySales, DemandHypothesis, Product
from app.services.history import forecast_for

MAX_DAYS = 14
FACTOR_RANGE = (0.3, 3.0)
VERDICT_LABEL = {"CORRECT": "Đúng", "PARTIAL": "Đúng một phần", "WRONG": "Sai"}


class HypothesisError(Exception):
    pass


def matching_products(db: Session, category: str | None, sku: str | None) -> tuple[list[Product], str | None, str | None]:
    """Tra ve (san pham, ten nhom chinh xac, sku chinh xac)."""
    if bool(category) == bool(sku):
        raise HypothesisError("Cần nêu đúng một phạm vi: một nhóm hàng hoặc một SKU.")
    if sku:
        p = db.scalar(select(Product).where(Product.sku == sku.upper()))
        if not p:
            raise HypothesisError(f"Không tìm thấy SKU {sku}")
        return [p], None, p.sku
    names = list(db.scalars(select(Product.category).where(Product.category.ilike(f"%{category}%")).distinct()))
    if not names:
        raise HypothesisError(f"Không tìm thấy nhóm hàng '{category}'")
    if len(names) > 1:
        raise HypothesisError(f"'{category}' khớp nhiều nhóm: {', '.join(sorted(names))}. Hãy nêu rõ một nhóm.")
    products = list(db.scalars(select(Product).where(Product.category == names[0], Product.status == "ACTIVE")))
    return products, names[0], None


def validate(db: Session, factor: float, start: date, end: date, reason: str, category: str | None,
             sku: str | None) -> None:
    if not FACTOR_RANGE[0] <= factor <= FACTOR_RANGE[1] or abs(factor - 1) < 0.01:
        raise HypothesisError(f"Hệ số phải trong khoảng {FACTOR_RANGE[0]}–{FACTOR_RANGE[1]} và khác 1.")
    if start < today():
        raise HypothesisError("Ngày bắt đầu không được ở quá khứ.")
    if end < start:
        raise HypothesisError("Ngày kết thúc phải sau ngày bắt đầu.")
    if (end - start).days + 1 > MAX_DAYS:
        raise HypothesisError(f"Giả thuyết chỉ áp dụng tối đa {MAX_DAYS} ngày.")
    if not reason or not reason.strip():
        raise HypothesisError("Cần ghi lý do của giả thuyết để đối chiếu về sau.")
    # Ca giao giua nhom va SKU trong nhom: neu khong he so nhan chong ma xem truoc va du bao nen khong biet
    if sku:
        own_category = db.scalar(select(Product.category).where(Product.sku == sku))
        scope = or_(DemandHypothesis.sku == sku, DemandHypothesis.category == own_category)
    else:
        scope = or_(DemandHypothesis.category == category,
                    DemandHypothesis.sku.in_(select(Product.sku).where(Product.category == category)))
    overlap = db.scalar(select(DemandHypothesis.id).where(
        DemandHypothesis.status == "ACTIVE", scope,
        DemandHypothesis.start_date <= end, DemandHypothesis.end_date >= start))
    if overlap:
        raise HypothesisError(f"Đã có giả thuyết #{overlap} trùng phạm vi (cùng nhóm hoặc SKU trong nhóm) trong khoảng ngày này.")


def preview(db: Session, products: list[Product], factor: float, start: date, end: date) -> dict:
    t = today()
    offset = (start - t).days
    days = (end - start).days + 1
    lines = []
    for p in products:
        fc = forecast_for(db, p, horizon=offset + days, start=t, with_hypotheses=False)
        base = sum(fc.daily[offset:])
        lines.append({"sku": p.sku, "name": p.name, "baseline": round(base, 1), "adjusted": round(base * factor, 1)})
    total = sum(l["baseline"] for l in lines)
    return {"baseline_total": round(total, 1), "adjusted_total": round(total * factor, 1), "sku_count": len(lines),
            "lines": sorted(lines, key=lambda l: -l["baseline"])[:8]}


def evaluate_finished(db: Session) -> list[dict]:
    """Cham cac gia thuyet da het han. Dung luong ban thuc te: cua hang that khong biet nhu cau bi hut."""
    done = []
    for x in db.scalars(select(DemandHypothesis).where(DemandHypothesis.status == "ACTIVE",
                                                       DemandHypothesis.end_date < today())):
        # Pham vi da chot luc duyet: so khop chinh xac, tim gan dung co the raise lam hong job sang
        in_scope = (Product.category == x.category, Product.status == "ACTIVE") if x.category else (Product.sku == x.sku,)
        ids = list(db.scalars(select(Product.id).where(*in_scope)))
        actual, stockouts = db.execute(
            select(func.coalesce(func.sum(DailySales.qty_sold), 0),
                   func.coalesce(func.sum(case((DailySales.stockout.is_(True), 1), else_=0)), 0))
            .where(DailySales.product_id.in_(ids), DailySales.date.between(x.start_date, x.end_date))
        ).one()
        ratio = float(actual) / x.baseline_total if x.baseline_total > 0 else 0.0
        verdict = hypothesis_verdict(x.factor, ratio)
        x.result = {"actual_total": int(actual), "baseline_total": x.baseline_total, "ratio": round(ratio, 3),
                    "verdict": verdict, "stockout_sku_days": int(stockouts)}
        x.status = "EVALUATED"
        audit.log(db, "system", "HYPOTHESIS_EVALUATED", "demand_hypothesis", x.id, x.result)
        done.append(view(x))
    return done


def view(x: DemandHypothesis) -> dict:
    r = x.result or {}
    return {"id": x.id, "scope": x.category or x.sku, "category": x.category, "sku": x.sku, "factor": x.factor,
            "start_date": x.start_date.isoformat(), "end_date": x.end_date.isoformat(), "reason": x.reason,
            "status": x.status, "baseline_total": x.baseline_total, "actual_total": r.get("actual_total"),
            "ratio": r.get("ratio"), "verdict": r.get("verdict"), "verdict_label": VERDICT_LABEL.get(r.get("verdict")),
            "stockout_sku_days": r.get("stockout_sku_days"), "created_by": x.created_by}


def list_views(db: Session, limit: int = 30) -> list[dict]:
    return [view(x) for x in db.scalars(select(DemandHypothesis).order_by(DemandHypothesis.id.desc()).limit(limit))]


def recently_evaluated(db: Session, days: int = 3) -> list[DemandHypothesis]:
    cutoff = today() - timedelta(days=days)
    return list(db.scalars(select(DemandHypothesis).where(DemandHypothesis.status == "EVALUATED",
                                                          DemandHypothesis.end_date >= cutoff)))
