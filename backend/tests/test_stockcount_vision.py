import base64
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.agent import tools as toolmod
from app.agent import vision
from app.agent.tools import ToolContext
from app.clock import today
from app.models import Lot, Product, Proposal, StockMovement, User
from app.proposals import builders, service
from app.services import stockcount as SC
from app.services.inventory import active_lots
from app.sim.world import REFERENCE_WORLD


def _mgr(db):
    return db.scalar(select(User).where(User.username == "quanly"))


def _product_with_stock(db, min_qty=4):
    lots = active_lots(db)
    return next(p for p in db.scalars(select(Product).order_by(Product.sku))
                if sum(l.qty_remaining for l in lots.get(p.id, [])) >= min_qty and p.status == "ACTIVE")


def _system(db, p):
    db.expire_all()
    return sum(l.qty_remaining for l in active_lots(db, [p.id]).get(p.id, []))


def _fresh_deadline(db, p):
    import datetime as dt
    p.expires_at = dt.datetime.now() + dt.timedelta(days=1)
    db.commit()


def test_sheet_is_blind(db):
    row = SC.sheet(db)[0]
    assert set(row) == {"sku", "name", "category"}


def test_no_difference_creates_nothing(db):
    p = _product_with_stock(db)
    prop, n = builders.stock_adjust(db, {p.sku: _system(db, p)}, "user:nhanvien")
    assert prop is None and n == 1


def test_count_changes_nothing_until_approved(db, outbox):
    p = _product_with_stock(db)
    system = _system(db, p)
    prop, _ = builders.stock_adjust(db, {p.sku: system - 2}, "user:nhanvien")
    db.commit()
    assert prop.status == "PENDING" and _system(db, p) == system
    _fresh_deadline(db, prop)
    out = service.approve(db, prop.id, _mgr(db))
    assert out.status == "EXECUTED", out.execution_result
    assert _system(db, p) == system - 2
    moves = db.scalars(select(StockMovement).where(StockMovement.type == "ADJUST", StockMovement.ref == f"proposal:{prop.id}")).all()
    assert sum(m.qty for m in moves) == -2


def test_overage_is_added_to_newest_lot(db, outbox):
    p = _product_with_stock(db)
    system = _system(db, p)
    prop, _ = builders.stock_adjust(db, {p.sku: system + 3}, "user:nhanvien")
    db.commit()
    _fresh_deadline(db, prop)
    assert service.approve(db, prop.id, _mgr(db)).status == "EXECUTED"
    assert _system(db, p) == system + 3


def test_stale_count_fails_instead_of_overwriting(db, outbox):
    p = _product_with_stock(db)
    system = _system(db, p)
    prop, _ = builders.stock_adjust(db, {p.sku: system - 1}, "user:nhanvien")
    db.commit()
    _fresh_deadline(db, prop)
    lot = db.scalar(select(Lot).where(Lot.product_id == p.id, Lot.status == "ACTIVE", Lot.qty_remaining > 0))
    lot.qty_remaining -= 1  # co hang ban ra giua luc dem va luc duyet
    db.commit()
    out = service.approve(db, prop.id, _mgr(db))
    assert out.status == "FAILED" and "đếm lại" in out.execution_result["error"]


def test_large_gap_warns():
    assert SC.is_large_gap(100, -25) and not SC.is_large_gap(100, -3) and not SC.is_large_gap(3, -2)


def test_invalid_count_rejected(db):
    with pytest.raises(SC.StockCountError):
        builders.stock_adjust(db, {"KHONGCO": 1}, "x")
    p = _product_with_stock(db)
    with pytest.raises(SC.StockCountError):
        builders.stock_adjust(db, {p.sku: -1}, "x")


def test_staff_can_submit_count_but_not_approve(client, staff, db):
    p = _product_with_stock(db)
    r = client.post("/api/stock-counts", headers=staff, json={"lines": [{"sku": p.sku, "counted_qty": _system(db, p) - 1}]})
    assert r.status_code == 200, r.text
    pid = r.json()["proposal"]["id"]
    assert client.post(f"/api/proposals/{pid}/approve", headers=staff).status_code == 403
    db.get(Proposal, pid).status = "EXPIRED"
    db.commit()


def test_form_tool_is_read_only(db):
    out = toolmod.REGISTRY["open_stock_count_form"].fn(ToolContext(db=db, user=_mgr(db)), category="Bia")
    assert toolmod.REGISTRY["open_stock_count_form"].kind == "read"
    assert out.ui[0]["form"] == "stock_count"
    assert "system_qty" not in out.ui[0]["lines"][0]


@pytest.mark.parametrize("text,expected", [
    ("HSD: 15/12/2026", date(2026, 12, 15)), ("15.12.26", date(2026, 12, 15)), ("EXP 2026-12-15", date(2026, 12, 15)),
    ("12/2026", date(2026, 12, 31)), ("02/2028", date(2028, 2, 29)), ("31/02/2026", None), ("abc", None), (None, None),
])
def test_parse_expiry(text, expected):
    assert vision.parse_expiry(text) == expected


def _stub(monkeypatch, reply):
    monkeypatch.setattr(vision, "_call_model", lambda *_: reply)


def test_read_expiry_ok(monkeypatch):
    d = today() + timedelta(days=5)
    _stub(monkeypatch, f'```json\n{{"hsd_text": "{d:%d/%m/%Y}", "nsx_text": null, "confidence": 0.9}}\n```')
    r = vision.read_expiry("AAAA", "image/jpeg", 7)
    assert r["expiry_date"] == d.isoformat() and r["warnings"] == []


@pytest.mark.parametrize("reply,needle", [
    ('{"hsd_text": null, "nsx_text": "01/01/2026", "confidence": 0.9}', "Không đọc được"),
    ('{"hsd_text": "01/01/2020", "nsx_text": null, "confidence": 0.9}', "đã qua"),
    ('{"hsd_text": "01/01/2030", "nsx_text": null, "confidence": 0.9}', "xa hơn"),
])
def test_read_expiry_warns(monkeypatch, reply, needle):
    _stub(monkeypatch, reply)
    assert any(needle in w for w in vision.read_expiry("AAAA", "image/png", 7)["warnings"])


def test_nsx_is_never_used_as_expiry(monkeypatch):
    _stub(monkeypatch, '{"hsd_text": null, "nsx_text": "01/12/2026", "confidence": 0.95}')
    assert vision.read_expiry("AAAA", "image/png")["expiry_date"] is None


def test_read_expiry_rejects_bad_input():
    with pytest.raises(vision.VisionError):
        vision.read_expiry("AAAA", "application/pdf")
    with pytest.raises(vision.VisionError):
        vision.read_expiry("A" * (vision.MAX_BASE64_CHARS + 1), "image/png")


def test_model_failure_is_a_clean_error(monkeypatch):
    def boom(*_):
        raise RuntimeError("429")
    monkeypatch.setattr(vision, "_call_model", boom)
    with pytest.raises(vision.VisionError, match="nhập HSD bằng tay"):
        vision.read_expiry(base64.b64encode(b"x").decode(), "image/png")


def test_vision_endpoint_writes_nothing(client, staff, db, monkeypatch):
    _stub(monkeypatch, '{"hsd_text": null, "nsx_text": null, "confidence": 0.1}')
    before = db.scalar(select(StockMovement.id).order_by(StockMovement.id.desc()))
    r = client.post("/api/vision/expiry", headers=staff, json={"image_base64": "AAAA", "mime_type": "image/png"})
    assert r.status_code == 200 and r.json()["expiry_date"] is None
    assert db.scalar(select(StockMovement.id).order_by(StockMovement.id.desc())) == before


def test_non_fefo_world_keeps_compliance_default():
    assert REFERENCE_WORLD.fefo_compliance == 1.0
    w = REFERENCE_WORLD.with_fefo(0.5)
    assert w.fefo_compliance == 0.5 and w.elasticity == REFERENCE_WORLD.elasticity
