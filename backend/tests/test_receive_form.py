"""Nhan hang qua chat bang form: tool chi MO form (khong ghi), viec nhan that van chi qua REST."""
import json

from sqlalchemy import func, select

from app.agent import tools as toolmod
from app.models import Lot, PurchaseOrder, User


def _ctx(db):
    return toolmod.ToolContext(db=db, user=db.scalar(select(User).where(User.role == "staff")))


def _sent_po(db):
    return db.scalars(select(PurchaseOrder).where(PurchaseOrder.status == "SENT")
                      .order_by(PurchaseOrder.id)).first()


def test_open_receive_form_emits_form_matching_po(db):
    po = _sent_po(db)
    assert po is not None
    out = toolmod.REGISTRY["open_receive_form"].fn(_ctx(db), po=po.code)
    (w,) = [u for u in out.ui if u["type"] == "widget"]
    assert w["kind"] == "form" and w["form"] == "receive_po"
    assert w["meta"]["po_id"] == po.id and w["meta"]["code"] == po.code
    assert w["submit"] == {"method": "POST", "path": f"/purchase-orders/{po.id}/receive"}
    assert {l["line_id"] for l in w["lines"]} == {l.id for l in po.lines}
    for l in w["lines"]:
        pl = next(x for x in po.lines if x.id == l["line_id"])
        assert l["sku"] == pl.product.sku and l["qty"] == pl.qty and l["default_expiry"]
    json.dumps(w, default=str)
    # LLM chi nhan tom tat ngan, khong co dong hang / widget
    assert out.data["form_shown"] is True and out.data["lines"] == len(po.lines)
    assert "lines_detail" not in out.data and "default_expiry" not in json.dumps(out.data)
    # tra theo id cung duoc
    assert toolmod.REGISTRY["open_receive_form"].fn(_ctx(db), po=str(po.id)).ui


def test_open_receive_form_errors(db):
    fn = toolmod.REGISTRY["open_receive_form"].fn
    out = fn(_ctx(db), po="PO-KHONG-CO")
    assert "error" in out.data and not out.ui
    done = db.scalars(select(PurchaseOrder).where(PurchaseOrder.status != "SENT")).first()
    if done:
        out = fn(_ctx(db), po=done.code)
        assert "error" in out.data and done.status in out.data["error"] and not out.ui


def test_form_tool_is_read_only_and_writes_nothing(db):
    t = toolmod.REGISTRY["open_receive_form"]
    assert t.kind == "read"
    po = _sent_po(db)
    lots = db.scalar(select(func.count()).select_from(Lot))
    t.fn(_ctx(db), po=po.code)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Lot)) == lots
    assert db.get(PurchaseOrder, po.id).status == "SENT"
    assert not any(n.startswith(("approve", "send", "execute", "delete", "update")) for n in toolmod.REGISTRY)
    assert {x.kind for x in toolmod.REGISTRY.values()} <= {"read", "propose"}


def test_receiving_only_happens_via_rest_endpoint(client, staff, db):
    po = _sent_po(db)
    out = toolmod.REGISTRY["open_receive_form"].fn(_ctx(db), po=po.code)
    (w,) = [u for u in out.ui if u["type"] == "widget"]
    body = {"lines": [{"line_id": l["line_id"], "received_qty": l["qty"], "expiry_date": l["default_expiry"]}
                      for l in w["lines"]]}
    r = client.post("/api/purchase-orders/" + str(w["meta"]["po_id"]) + "/receive", json=body, headers=staff)
    assert r.status_code == 200, r.text
    assert r.json()["code"] == po.code
    db.expire_all()
    assert db.get(PurchaseOrder, po.id).status == "RECEIVED"
    # don da nhan -> mo form lai bi tu choi, bam dup cung bi chan o REST
    assert "error" in toolmod.REGISTRY["open_receive_form"].fn(_ctx(db), po=po.code).data
    assert client.post(f"/api/purchase-orders/{po.id}/receive", json=body, headers=staff).status_code == 422
