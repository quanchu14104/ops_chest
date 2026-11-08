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
    pend = client.get("/api/proposals?status=PENDING&limit=200", headers=manager).json()
    item = next((i for i in d["items"] if i["id"] == "pending"), None)
    assert (item["count"] if item else 0) == len(pend)
