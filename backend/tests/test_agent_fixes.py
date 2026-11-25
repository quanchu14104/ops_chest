"""Hoi quy cho cac loi tro ly tim thay khi test vai Store Manager (20/11/2026)."""
import json

import pytest
from sqlalchemy import select

from app.agent import orchestrator
from app.agent import tools as toolmod
from app.agent.prompts import system_prompt
from app.models import Product, Proposal
from tests.test_hitl import ScriptedLLM, _session
from tests.test_revise import _ctx, _mk_po


@pytest.fixture(autouse=True)
def _release_purchase_orders(db):
    """DB test dung chung giua cac file: sau moi test, cho het han de xuat dat hang cua ngay va go dedupe_key, de
    test sau (vd test_hitl) goi propose_purchase_order van tao de xuat MOI thay vi dung lai de xuat cua file nay."""
    yield
    db.rollback()
    for p in db.scalars(select(Proposal).where(Proposal.type == "PURCHASE_ORDER")):
        if p.status == "PENDING":
            p.status = "EXPIRED"
        if p.dedupe_key and not p.dedupe_key.startswith("old-"):
            p.dedupe_key = f"old-{p.id}"
    db.commit()


class RateLimitError(Exception):
    """Cung ten voi loi cua SDK openai; noi dung gia lap loi Groq that (co ma to chuc, link thanh toan)."""
    status_code = 429


class TooLarge(Exception):
    status_code = 413


class FailingLLM:
    def __init__(self, errors, then_text="Xong."):
        self.errors = list(errors)
        self.then_text = then_text
        self.calls: list[list[dict]] = []

    def stream_chat(self, messages, tools):
        self.calls.append(messages)
        if self.errors:
            raise self.errors.pop(0)
        yield ("text", self.then_text)
        yield ("finish", "stop")


# ---- L-02: loi LLM khong hien nguyen van cho SM
def test_rate_limit_error_is_shown_in_plain_vietnamese_without_provider_details(db):
    s, u = _session(db)
    err = RateLimitError("Error code: 429 - Rate limit reached in organization `org_01abc` on tokens per minute "
                         "(TPM): Limit 8000. Upgrade to Dev Tier today at https://console.groq.com/settings/billing")
    events = list(orchestrator.run_turn(db, s, u, "Lô nào sắp hết hạn?", llm=FailingLLM([err])))
    msg = next(e for e in events if e["type"] == "error")["message"]
    assert "giới hạn lượt gọi" in msg
    assert "org_" not in msg and "billing" not in msg and "429" not in msg
    assert events[-1]["metrics"]["outcome"] == "llm_error:rate_limit"


def test_request_too_large_retries_once_with_compact_context(db):
    s, u = _session(db)
    list(orchestrator.run_turn(db, s, u, "Tổng quan kho?", llm=ScriptedLLM([{"text": "Kho ổn."}])))
    llm = FailingLLM([TooLarge("Error code: 413 - Request too large for model in organization `org_x`")],
                     then_text="Đây là 10 món.")
    events = list(orchestrator.run_turn(db, s, u, "Kể 10 món hết hàng", llm=llm))
    assert not [e for e in events if e["type"] == "error"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Đây là 10 món."
    full, compact = llm.calls
    assert [m["content"] for m in compact if m["role"] == "user"] == ["Kể 10 món hết hàng"]
    assert len(compact) < len(full)


def test_second_too_large_gives_a_plain_message(db):
    s, u = _session(db)
    llm = FailingLLM([TooLarge("413 Request too large"), TooLarge("413 Request too large")])
    events = list(orchestrator.run_turn(db, s, u, "Kể 10 món hết hàng", llm=llm))
    msg = next(e for e in events if e["type"] == "error")["message"]
    assert "quá nhiều dữ liệu" in msg and len(llm.calls) == 2


# ---- L-03: nhan vo "Đã tạo đề xuất #N" cho de xuat khong do luot nay tao
def test_claiming_a_proposal_not_created_this_turn_is_flagged(db):
    s, u = _session(db)
    events = list(orchestrator.run_turn(db, s, u, "Hôm nay nên đặt gì?",
                                        llm=ScriptedLLM([{"text": "Đã tạo đề xuất #999 (chờ duyệt)."}])))
    guard = [e for e in events if e["type"] == "guard"]
    assert guard and guard[0]["false_exec"] is True


def test_claiming_a_proposal_created_this_turn_is_not_flagged(db):
    old = _mk_po(db)
    supplier = old.payload["supplier_code"]
    old.status = "EXPIRED"
    old.dedupe_key = f"old-{old.id}"
    db.commit()
    s, u = _session(db)

    class Claim(ScriptedLLM):
        def stream_chat(self, messages, tools):
            if self.steps:
                yield from super().stream_chat(messages, tools)
                return
            pid = json.loads(messages[-1]["content"])["proposal_id"]
            yield ("text", f"Đã tạo đề xuất #{pid}, chờ anh/chị duyệt trong Hộp duyệt.")
            yield ("finish", "stop")

    events = list(orchestrator.run_turn(db, s, u, "Đặt hàng đi",
                                        llm=Claim([{"calls": [("propose_purchase_order", {"supplier": supplier})]}])))
    assert not [e for e in events if e["type"] == "guard" and e["false_exec"]]
    # Don dep: het han VA go dedupe_key, de test khac goi propose_purchase_order van nhan de xuat MOI cua phien no
    for p in db.scalars(select(Proposal).where(Proposal.chat_session_id == s.id)):
        p.status = "EXPIRED"
        p.dedupe_key = f"old-{p.id}"
    db.commit()


# ---- L-01: "đặt thêm 50 cà rốt" vao don dang cho duyet, ke ca mon chua co trong don
def test_revise_adds_an_item_of_the_same_supplier(db):
    old = _mk_po(db)
    in_order = {l["sku"] for l in old.payload["lines"]}
    extra = db.scalars(select(Product).where(Product.supplier_id == old.payload["supplier_id"],
                                             Product.sku.not_in(in_order))).first()
    other = db.scalars(select(Product).where(Product.supplier_id != old.payload["supplier_id"])).first()
    t = toolmod.REGISTRY["revise_proposal"].fn
    assert "error" in t(_ctx(db), proposal_id=old.id, sku_qty=[{"sku": other.sku, "qty": 5}]).data
    if extra is None:
        return
    out = t(_ctx(db), proposal_id=old.id, sku_qty=[{"sku": extra.sku, "qty": 50}]).data
    new = db.get(Proposal, out["proposal_id"])
    line = next(l for l in new.payload["lines"] if l["sku"] == extra.sku)
    assert line["qty"] == 50 and line["added_in_chat"] is True
    assert new.payload["total_value"] == sum(l["qty"] * l["unit_cost"] for l in new.payload["lines"])
    db.refresh(old)
    assert old.status == "SUPERSEDED" and new.status == "PENDING"
    new.status = "EXPIRED"
    db.commit()


# ---- L-02: liet ke mon dang het, ban chay nhat truoc
def test_search_products_lists_out_of_stock_best_sellers_first(db):
    rows = toolmod.REGISTRY["search_products"].fn(_ctx(db), out_of_stock=True, limit=10).data
    assert len(rows) <= 10
    assert all(r["on_hand"] == 0 and r["status"] == "ACTIVE" for r in rows)
    sold = [r["sold_28d"] for r in rows]
    assert sold == sorted(sold, reverse=True)


def test_prompt_forbids_free_text_orders_invented_units_and_tool_names():
    p = system_prompt("Trần Minh Anh", "manager")
    assert "NEVER write a proposal, order letter or email as free text" in p
    assert '"tặng"' in p and 'never "bạn"' in p and "out_of_stock=true" in p


def test_prompt_declines_off_topic_questions():
    """Cau hoi ngoai nghiep vu: tu choi mot cau, khong goi tool (giu han muc LLM cho viec kho)."""
    for role in ("manager", "staff"):
        p = system_prompt("Trần Minh Anh", role)
        assert "only this store's operations" in p and "call no tool" in p
        assert "Em chỉ hỗ trợ việc kho và hạn sử dụng của cửa hàng" in p


def test_revise_sku_add_adds_to_the_current_quantity(db):
    old = _mk_po(db)
    line = old.payload["lines"][0]
    t = toolmod.REGISTRY["revise_proposal"].fn
    assert "error" in t(_ctx(db), proposal_id=old.id, sku_add=[{"sku": line["sku"], "qty": 0}]).data
    out = t(_ctx(db), proposal_id=old.id, sku_add=[{"sku": line["sku"], "qty": 50}]).data
    new = db.get(Proposal, out["proposal_id"])
    assert next(l for l in new.payload["lines"] if l["sku"] == line["sku"])["qty"] == line["qty"] + 50
