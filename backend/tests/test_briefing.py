"""Ban tin dau ngay: tat dinh, khong can LLM, can quyen dang nhap."""


def test_briefing_requires_login(client):
    assert client.get("/api/briefing").status_code in (401, 403)


def test_briefing_is_deterministic_and_has_prompts(client, manager):
    a = client.get("/api/briefing", headers=manager)
    assert a.status_code == 200
    d = a.json()
    assert d["today"] == "2026-11-07" and d["date_label"] == "07/11/2026"
    assert d["all_clear"] == (not d["items"])
    for it in d["items"]:
        assert it["level"] in ("action", "warn", "info") and it["text"] and it["prompt"] and it["count"] > 0
    assert client.get("/api/briefing", headers=manager).json() == d


def test_briefing_pending_count_matches_inbox(client, manager, staff):
    d = client.get("/api/briefing", headers=staff).json()  # nhan vien cung xem duoc
    # Hop duyet (InboxPanel) lay ca de xuat loi khi thuc hien: SM van phai thu lai hoac tu choi
    pend = client.get("/api/proposals?status=PENDING,FAILED&limit=200", headers=manager).json()
    item = next((i for i in d["items"] if i["id"] == "pending"), None)
    assert (item["count"] if item else 0) == len(pend)


def test_briefing_items_have_valid_quick_keys(client, manager):
    """Moi muc ban tin co `quick` (neu co) phai chay duoc qua /api/chat/quick, khong can LLM."""
    d = client.get("/api/briefing", headers=manager).json()
    for it in d["items"]:
        if it.get("quick"):
            r = client.get(f"/api/chat/quick/{it['quick']}", headers=manager)
            assert r.status_code == 200, (it["quick"], r.text)
            assert r.json()["ui"] and all(u["type"] == "widget" for u in r.json()["ui"])


def test_briefing_staff_wording_is_not_for_manager(db):
    """Nhan vien khong duyet duoc: muc de xuat la thong tin, khong xung "anh/chi duyet" (L-11).

    Them mot de xuat cho duyet trong phien rieng roi rollback, khong de lai du lieu cho test khac.
    """
    from datetime import datetime

    from app.models import Proposal
    from app.services import briefing

    db.add(Proposal(type="MARKDOWN", status="PENDING", title="t", rationale="r", payload={}, original_payload={},
                    created_by="job", created_at=datetime(2026, 11, 7, 6, 30)))
    db.flush()
    try:
        pm = next(i for i in briefing.build(db, role="manager")["items"] if i["id"] == "pending")
        ps = next(i for i in briefing.build(db, role="staff")["items"] if i["id"] == "pending")
    finally:
        db.rollback()
    assert pm["level"] == "action" and "anh/chị duyệt" in pm["text"]
    assert ps["level"] == "info" and "Store Manager duyệt" in ps["text"] and ps["count"] == pm["count"]


def test_briefing_due_item_is_short_with_detail(client, manager):
    d = client.get("/api/briefing", headers=manager).json()
    due = next((i for i in d["items"] if i["id"] == "due"), None)
    if due is None:
        return
    assert len(due["detail"]) == due["count"]
    if due["count"] > 1:
        assert not any(name in due["text"] for name in due["detail"])


def test_briefing_expiring_value_matches_counted_lots(client, manager):
    """So lo va tong tien cua muc "nguy co huy" phai cung mot tap lo (L-08)."""
    d = client.get("/api/briefing", headers=manager).json()
    item = next((i for i in d["items"] if i["id"] == "expiring"), None)
    if item is None:
        return
    lots = client.get("/api/inventory/expiring?days=3", headers=manager).json()["lots"]
    near = [l for l in lots if l["status"] not in ("OK", "EXPIRED")]
    assert item["count"] == len(near)
    expected = f"{sum(l['value_at_risk'] for l in near):,}".replace(",", ".")
    assert expected in item["text"]
