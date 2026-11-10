"""Dang nhap, dashboard, ton kho, san pham, NCC, PO, bao cao, audit."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.auth import create_token, current_user, require_manager, verify_password
from app.clock import today
from app.config import settings
from app.db import get_db
from app.models import AuditLog, Proposal, PurchaseOrder, Supplier, User
from app.proposals.views import acceptance_stats
from app.services import briefing as briefing_svc
from app.services import charts, inventory, receiving, replenish, reports
from app.services.history import abc_xyz_classes
from app.services.receiving import ReceiveError

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    return {"token": create_token(u.username, u.role),
            "user": {"username": u.username, "full_name": u.full_name, "role": u.role}}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"username": user.username, "full_name": user.full_name, "role": user.role}


@router.get("/meta")
def meta():
    return {"today": today().isoformat(), "store_name": settings.store_name, "llm_model": settings.llm_model,
            "llm_base_url": settings.llm_base_url, "llm_model_fallback": settings.llm_model_fallback or None,
            "llm_configured": bool(settings.llm_api_key)
            or "localhost" in settings.llm_base_url}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    summ = inventory.inventory_summary(db)
    kpi = reports.kpi_compare(db, 30)
    exp = inventory.expiring_lots(db, days=3, with_options=False)
    pending = db.scalars(select(Proposal).where(Proposal.status == "PENDING").order_by(Proposal.id.desc())).all()
    due = replenish.suppliers_due(db)
    return {
        "today": today().isoformat(), "inventory": summ,
        "kpi_current": kpi["current"], "kpi_previous": kpi["previous"],
        "expiring": {"summary": exp["summary"], "total_value_at_risk": exp["total_value_at_risk"],
                     "lots": [l for l in exp["lots"] if l["status"] != "OK"][:8]},
        "pending": [{"id": p.id, "type": p.type, "title": p.title, "est_value": p.est_value,
                     "created_by": p.created_by, "expires_at": p.expires_at.isoformat() if p.expires_at else None}
                    for p in pending],
        "suppliers_due_today": [{"code": s.code, "name": s.name} for s in due],
        "agent_acceptance": acceptance_stats(db),
        "daily": reports.sales_series(db, today() - timedelta(days=30), today() - timedelta(days=1)),
    }


@router.get("/briefing")
def briefing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return briefing_svc.build(db)


@router.get("/inventory/summary")
def inv_summary(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return inventory.inventory_summary(db)


@router.get("/inventory/expiring")
def inv_expiring(days: int = Query(7, ge=0, le=120), category: str | None = None,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    return inventory.expiring_lots(db, days=days, category=category)


@router.get("/products")
def products(query: str | None = None, category: str | None = None, limit: int = Query(300, le=500),
             db: Session = Depends(get_db), user: User = Depends(current_user)):
    prods = inventory.find_products(db, query, category, limit)
    lots = inventory.active_lots(db, [p.id for p in prods])
    classes = abc_xyz_classes(db)
    return [{"sku": p.sku, "name": p.name, "category": p.category, "status": p.status, "is_new": reports.is_new(p),
             "listed_date": p.listed_date.isoformat() if p.listed_date else None,
             "max_stock_qty": p.max_stock_qty, "min_display_qty": p.min_display_qty,
             "freshness_class": p.freshness_class, "shelf_life_days": p.shelf_life_days, "unit_cost": p.unit_cost,
             "unit_price": p.unit_price, "pack_size": p.pack_size, "supplier": p.supplier.name,
             "is_traffic_driver": p.is_traffic_driver,
             "abc_xyz": None if reports.is_new(p) else classes[p.sku].cell if p.sku in classes else None,
             "on_hand": sum(l.qty_remaining for l in lots.get(p.id, []))} for p in prods]


@router.get("/products/{sku}")
def product(sku: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = inventory.product_detail(db, sku.upper())
    if not d:
        raise HTTPException(404, "Không tìm thấy SKU")
    return d


@router.get("/suppliers")
def suppliers(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Supplier).options(joinedload(Supplier.agreements)).order_by(Supplier.code)).unique()
    out = []
    for s in rows:
        a = s.agreement_on(today())
        out.append({"id": s.id, "code": s.code, "name": s.name, "email": s.email, "phone": s.phone,
                    "lead_time_days": s.lead_time_days, "order_weekdays": s.order_weekdays,
                    "min_order_value": s.min_order_value,
                    "agreement": None if not a else {
                        "discount_pct": a.discount_pct, "accepts_near_expiry_return": a.accepts_near_expiry_return,
                        "return_min_days_before_expiry": a.return_min_days_before_expiry,
                        "return_credit_pct": a.return_credit_pct, "valid_from": a.valid_from.isoformat(),
                        "valid_to": a.valid_to.isoformat(), "notes": a.notes}})
    return out


@router.get("/purchase-orders")
def purchase_orders(status: str | None = None, limit: int = Query(50, le=300),
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = select(PurchaseOrder).options(joinedload(PurchaseOrder.supplier)).order_by(
        PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()).limit(limit)
    if status:
        q = q.where(PurchaseOrder.status == status.upper())
    t = today()
    return [{"id": po.id, "code": po.code, "supplier": po.supplier.name, "status": po.status,
             "order_date": po.order_date.isoformat(), "expected_date": po.expected_date.isoformat(),
             "total_value": po.total_value, "proposal_id": po.proposal_id, "has_pdf": bool(po.pdf_path),
             "overdue_days": max(0, (t - po.expected_date).days) if po.status == "SENT" else 0}
            for po in db.scalars(q)]


@router.get("/purchase-orders/{po_id}")
def purchase_order(po_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, "Không tìm thấy đơn hàng")
    return {"id": po.id, "code": po.code, "status": po.status, "supplier": po.supplier.name,
            "order_date": po.order_date.isoformat(), "expected_date": po.expected_date.isoformat(),
            "total_value": po.total_value, "proposal_id": po.proposal_id, "has_pdf": bool(po.pdf_path),
            "reject_reasons": receiving.REJECT_REASONS,
            "lines": [{"line_id": l.id, "sku": l.product.sku, "name": l.product.name, "qty": l.qty,
                       "unit_cost": l.unit_cost, "received_qty": l.received_qty, "rejected_qty": l.rejected_qty,
                       "reject_reason": l.reject_reason, "short_qty": l.short_qty,
                       "actual_unit_cost": l.actual_unit_cost, "pack_size": l.product.pack_size,
                       "shelf_life_days": l.product.shelf_life_days,
                       "min_remaining_days": receiving.min_remaining_days(l.product.shelf_life_days),
                       "over_tolerance": receiving.over_tolerance(l.qty, l.product.pack_size),
                       "default_expiry": receiving.default_expiry(l.product.shelf_life_days).isoformat()}
                      for l in po.lines]}


@router.get("/purchase-orders/{po_id}/pdf")
def purchase_order_pdf(po_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    po = db.get(PurchaseOrder, po_id)
    if not po or not po.pdf_path or not Path(po.pdf_path).exists():
        raise HTTPException(404, "Đơn này không có file PDF")
    return FileResponse(po.pdf_path, media_type="application/pdf", filename=f"{po.code}.pdf")


class ReceiveLot(BaseModel):
    qty: int
    expiry_date: date | None = None


class ReceiveLine(BaseModel):
    line_id: int
    received_qty: int | None = None
    expiry_date: date | None = None
    # Mot dong giao nhieu HSD: moi cap (so luong, HSD) thanh mot lo. Co `lots` thi bo qua received_qty/expiry_date.
    lots: list[ReceiveLot] | None = None
    rejected_qty: int | None = None
    reject_reason: str | None = None
    actual_unit_cost: int | None = None
    # Chi co tac dung khi nguoi nhan la Store Manager
    accept_short_dated: bool = False
    accept_over: bool = False


class ReceiveIn(BaseModel):
    lines: list[ReceiveLine]


@router.post("/purchase-orders/{po_id}/receive")
def receive(po_id: int, body: ReceiveIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        return receiving.receive_po(db, po_id, [l.model_dump(exclude_none=True) for l in body.lines], user)
    except ReceiveError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e


class CancelPoIn(BaseModel):
    reason: str


@router.post("/purchase-orders/{po_id}/cancel")
def cancel_po(po_id: int, body: CancelPoIn, db: Session = Depends(get_db), user: User = Depends(require_manager)):
    try:
        return receiving.cancel_po(db, po_id, body.reason, user)
    except ReceiveError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e


@router.get("/reports/cost")
def cost(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    s, e = reports.default_range(start, end)
    return reports.cost_report(db, s, e)


@router.get("/reports/abc-xyz")
def abc(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return reports.abc_xyz_report(db)


@router.get("/reports/delist")
def delist(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return reports.delist_report(db)


@router.get("/charts")
def chart(metric: str, start: date | None = None, end: date | None = None, group_by: str = "day",
          category: str | None = None, sku: str | None = None, db: Session = Depends(get_db),
          user: User = Depends(current_user)):
    try:
        return charts.build_chart(db, metric, start, end, group_by, category, sku)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


_backtest_cache: dict = {}


@router.get("/reports/backtest")
def backtest(days: int = Query(60, ge=14, le=120), user: User = Depends(current_user)):
    """Mo phong A/B tren cung nhu cau: chinh sach 'kinh nghiem' vs Ops Chest. Mat ~10-30 giay."""
    from app.sim.backtest import run_backtest

    start = today() - timedelta(days=days)
    key = (start, days)
    if key not in _backtest_cache:
        _backtest_cache[key] = run_backtest(start, days)
    return _backtest_cache[key]


@router.get("/reports/backtest/sensitivity")
def backtest_sensitivity(user: User = Depends(current_user)):
    """Bang do nhay da tinh san (python -m app.sim.backtest --sensitivity): chay song mat vai phut."""
    from app.sim.backtest import SENSITIVITY_FILE

    if not SENSITIVITY_FILE.exists():
        raise HTTPException(404, "Chưa có bảng độ nhạy. Chạy: python -m app.sim.backtest --sensitivity")
    return json.loads(SENSITIVITY_FILE.read_text(encoding="utf-8"))


@router.get("/audit")
def audit_log(limit: int = Query(100, le=500), db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    return [{"id": a.id, "ts": a.ts.isoformat(), "actor": a.actor, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "detail": a.detail} for a in rows]


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return {"ok": True, "proposals": db.scalar(select(func.count()).select_from(Proposal))}
