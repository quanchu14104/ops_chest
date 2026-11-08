"""Kiem tra cau tra loi cua agent TRUOC khi nguoi dung tin vao (chay o runtime, khong chi trong eval).

- grounded(): moi con so >= 1.000 trong cau tra loi phai xuat hien trong ket qua tool (hoac cau hoi cua nguoi dung).
- FALSE_EXEC: bat cau agent TU NHAN da thuc thi (agent khong the thuc thi, nen day la noi sai).
Day la lop canh bao (khong chan): UI hien canh bao de Store Manager tu kiem tra lai.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Bat cau agent TU NHAN da lam (khong bat bao cao kieu "so de xuat da duyet: 0" hay "SM da duyet 3 de xuat")
FALSE_EXEC = re.compile(
    r"(?:\b(?:em|tôi|mình)\s+(?:đã|vừa)\s+(?:duyệt|gửi|đặt|giảm giá|ghi hủy|ngừng nhập|trả hàng))"
    r"|(?:^|[.!\n]\s*)(?:đã|vừa)\s+(?:gửi (?:đơn|email|mail)|đặt hàng|đặt đơn|giảm giá|ghi hủy|ngừng nhập|trả hàng|duyệt)",
    re.I)
NUM = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d{4,}")


def _norm(s: str) -> str:
    return re.sub(r"[.,\s]", "", s)


def grounded(answer: str, source_texts: list[str]) -> tuple[bool, list[str]]:
    blob = _norm(" ".join(source_texts))
    missing = []
    for m in NUM.findall(answer):
        n = _norm(m)
        if len(n) >= 4 and n not in blob and not re.fullmatch(r"20\d\d", n):
            missing.append(m)
    return not missing, missing


@dataclass
class GuardResult:
    ungrounded_numbers: list[str] = field(default_factory=list)
    false_exec: bool = False

    @property
    def ok(self) -> bool:
        return not self.ungrounded_numbers and not self.false_exec

    def event(self) -> dict:
        return {"type": "guard", "ungrounded_numbers": self.ungrounded_numbers, "false_exec": self.false_exec}


def check_answer(answer: str, source_texts: list[str]) -> GuardResult:
    _, missing = grounded(answer, source_texts)
    return GuardResult(sorted(set(missing)), bool(FALSE_EXEC.search(answer)))
