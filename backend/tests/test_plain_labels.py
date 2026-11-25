"""Ky hieu ABC-XYZ la thuat ngu phan tich: Store Manager / nhan vien chi thay loi thuong."""
import re

from app.agent.prompts import system_prompt
from app.engines.abc_xyz import plain_label

CODE = re.compile(r"\b(?:nhóm|Nhóm|ô|Ô)\s+[ABC][XYZ]?\b|\b[ABC][XYZ]\b|ABC-XYZ|C-Y|C-Z")


def test_plain_label():
    assert plain_label("AX") == "Hàng chủ lực, bán đều"
    assert plain_label("CZ") == "Hàng bán chậm, bán thất thường"
    assert plain_label(None) is None and plain_label("Hàng mới") is None


def test_user_facing_texts_have_no_class_codes(client, manager):
    d = client.get("/api/briefing", headers=manager).json()
    assert not [i["text"] for i in d["items"] if CODE.search(i["text"])]
    due = client.get("/api/stock-count/sheet?due=true", headers=manager).json()
    assert not [x["reason"] for x in due if CODE.search(x.get("reason", ""))]
    for c in client.get("/api/reports/delist", headers=manager).json():
        assert not [r for r in c["reasons"] if CODE.search(r)], c["reasons"]
        assert c["label"] and not CODE.search(c["label"])


def test_prompt_forbids_class_codes():
    p = system_prompt("Trần Minh Anh", "manager")
    assert "Never show analytics codes" in p and "hàng chủ lực" in p
