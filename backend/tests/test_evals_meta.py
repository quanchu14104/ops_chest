"""Kiem tra bo eval KHONG can LLM: cau hoi tham chieu tool co that, va cac ham cham diem hoat dong."""
from app.agent import evals
from app.agent import tools as toolmod


def test_eval_cases_reference_real_tools():
    assert len(evals.CASES) >= 30
    for c in evals.CASES:
        assert c.tools and all(t in toolmod.REGISTRY for t in c.tools), c.q


def test_eval_covers_chat_first_features():
    names = {t for c in evals.CASES for t in c.tools}
    assert {"revise_proposal", "open_receive_form", "open_pull_form", "open_date_check_form", "propose_write_off"} <= names
    assert {c.widget for c in evals.CASES if c.widget} == {"table", "kpis"}
    assert any(c.no_receive for c in evals.CASES)


def test_repeated_numbers_detects_copying_widget_rows():
    w = [{"kind": "table", "rows": [{"v": 1250000}, {"v": 53615}, {"v": 8}], "items": None}]
    assert evals.repeated_numbers("Tổng giá vốn 53.615đ và 1.250.000đ", w) == ["1.250.000", "53.615"]
    assert evals.repeated_numbers("Có 8 lô cần xử lý, ưu tiên lô gần hạn nhất.", w) == []  # so nho khong tinh
    assert evals.repeated_numbers("Doanh thu 9.999.999đ", w) == []  # so khong co trong widget


def test_received_pattern_flags_false_receipt_only():
    assert evals.RECEIVED.search("Em đã nhận hàng và cập nhật tồn kho")
    assert evals.RECEIVED.search("Đã cập nhật tồn kho xong")
    assert not evals.RECEIVED.search("Em đã mở form nhận hàng, anh/chị bấm xác nhận nhé")
