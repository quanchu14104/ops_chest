from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.agent import tools as toolmod
from app.agent.tools import ToolContext
from app.clock import today
from app.engines.edit_learning import EditObservation, detect_patterns, suggested_factor
from app.engines.forecast import forecast_demand, hypothesis_verdict
from app.models import DemandHypothesis, OrderAdjustment, Product, Proposal, User
from app.proposals import builders, service
from app.services import hypotheses as H
from app.services import learning
from app.services.history import forecast_for
from app.services.replenish import apply_order_adjustment, get_supplier, suggest_po


def _mgr(db):
    return db.scalar(select(User).where(User.username == "quanly"))


def _category(db):
    return db.scalar(select(Product.category).where(Product.category.ilike("%Bia%")))


@pytest.mark.parametrize("factor,ratio,expected", [
    (1.5, 1.5, "CORRECT"), (1.5, 1.3, "CORRECT"), (1.5, 1.2, "PARTIAL"), (1.5, 1.05, "WRONG"), (1.5, 0.9, "WRONG"),
    (0.5, 0.6, "CORRECT"), (0.5, 1.0, "WRONG"),
])
def test_verdict(factor, ratio, expected):
    assert hypothesis_verdict(factor, ratio) == expected


def test_skip_dates_exclude_event_from_level():
    end = date(2026, 3, 31)
    history = [10.0] * 56
    history[-1] = history[-2] = 100.0
    spiked = forecast_demand(history, end, 1, event_factors={})
    skipped = forecast_demand(history, end, 1, event_factors={}, skip_dates={end, end - timedelta(days=1)})
    assert skipped.level == pytest.approx(10, abs=0.5)
    assert spiked.level > skipped.level + 1


def test_hypothesis_changes_forecast_only_after_approval(db, outbox):
    cat = _category(db)
    product = db.scalar(select(Product).where(Product.category == cat, Product.status == "ACTIVE"))
    t = today()
    start, end = t + timedelta(days=1), t + timedelta(days=2)
    before = forecast_for(db, product, horizon=3, start=t).daily[1]
    p, created = builders.demand_hypothesis(db, "agent", 1.5, start, end, "Có trận bóng", category=cat)
    db.commit()
    assert created and p.status == "PENDING" and p.payload["sku_count"] > 0
    assert forecast_for(db, product, horizon=3, start=t).daily[1] == pytest.approx(before)

    out = service.approve(db, p.id, _mgr(db))
    assert out.status == "EXECUTED", out.execution_result
    row = db.get(DemandHypothesis, out.execution_result["hypothesis_id"])
    assert forecast_for(db, product, horizon=3, start=t).daily[1] == pytest.approx(before * 1.5, rel=0.02)

    with pytest.raises(H.HypothesisError):
        builders.demand_hypothesis(db, "agent", 1.2, start, end, "Trùng khoảng ngày", category=cat)
    row.status = "CANCELLED"
    db.commit()


@pytest.mark.parametrize("factor,start,end,reason,msg", [
    (5.0, 1, 2, "x", "Hệ số"), (1.5, -1, 2, "x", "quá khứ"), (1.5, 3, 2, "x", "sau ngày"),
    (1.5, 1, 30, "x", "tối đa"), (1.5, 1, 2, " ", "lý do"),
])
def test_hypothesis_validation(db, factor, start, end, reason, msg):
    t = today()
    with pytest.raises(H.HypothesisError, match=msg):
        builders.demand_hypothesis(db, "agent", factor, t + timedelta(days=start), t + timedelta(days=end), reason,
                                   category=_category(db))


def test_tool_only_proposes(db):
    ctx = ToolContext(db=db, user=_mgr(db))
    t = today()
    out = toolmod.REGISTRY["propose_demand_hypothesis"].fn(
        ctx, factor=1.3, start_date=(t + timedelta(days=3)).isoformat(), end_date=(t + timedelta(days=3)).isoformat(),
        reason="Khuyến mãi", category=_category(db))
    assert "error" not in out.data, out.data
    assert db.get(Proposal, out.data["proposal_id"]).status == "PENDING"
    assert toolmod.REGISTRY["propose_demand_hypothesis"].kind == "propose"


def test_pattern_needs_enough_consistent_edits():
    obs = [EditObservation("A", i % 3, 0.8) for i in range(6)]
    found = detect_patterns(obs)
    assert found[0]["factor"] == 0.8 and found[0]["proposals"] == 3
    assert detect_patterns(obs[:4]) == []
    assert detect_patterns([EditObservation("A", i, 0.8) for i in range(1)] * 6) == []
    mixed = [EditObservation("A", i, 0.7 if i % 2 else 1.1) for i in range(8)]
    assert detect_patterns(mixed) == []
    assert detect_patterns([EditObservation("A", i, 0.95) for i in range(8)]) == []


def test_factor_is_bounded():
    assert suggested_factor(0.1) == 0.5 and suggested_factor(9) == 1.5 and suggested_factor(0.83) == 0.85


def test_adjustment_rounds_to_pack_and_respects_cap():
    assert apply_order_adjustment(24, 0.8, 6, 100) == 18
    assert apply_order_adjustment(20, 1.5, 1, 25) == 25


def test_adjustment_needs_history_and_approval(db):
    p, _, err = builders.order_adjustment(db, "Không có nhóm này", "agent")
    assert p is None and "Chưa đủ" in err

    from app.sim.demo import seed_edit_history

    res = seed_edit_history(db, "quanly")
    assert seed_edit_history(db, "quanly")["created"] == 0
    p, created, err = builders.order_adjustment(db, res["category"], "agent")
    db.commit()
    assert created and p.status == "PENDING", err
    assert p.payload["factor"] == 0.8
    assert res["category"] not in learning.active_adjustments(db)
    out = service.approve(db, p.id, _mgr(db))
    assert out.status == "EXECUTED", out.execution_result
    assert learning.active_adjustments(db)[res["category"]].factor == 0.8
    assert all(x["category"] != res["category"] for x in learning.patterns(db))
    product = db.scalar(select(Product).where(Product.category == res["category"], Product.status == "ACTIVE"))
    sug = suggest_po(db, get_supplier(db, product.supplier_id))
    lines = [l for l in sug["lines"] if l["explain"]["order_adjustment"] == 0.8]
    assert lines and all(l["qty"] <= l["explain"]["qty_before_adjustment"] for l in lines)
    for a in db.scalars(select(OrderAdjustment)):
        a.active = False
    db.commit()


def test_cancel_requires_manager(client, staff):
    assert client.post("/api/hypotheses/1/cancel", headers=staff).status_code == 403
    assert client.post("/api/sim/advance", headers=staff, json={"days": 1}).status_code == 403
