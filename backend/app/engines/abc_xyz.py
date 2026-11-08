"""Phan tich ABC-XYZ.

- ABC: xep hang theo loi nhuan gop SAU HUY (doanh thu - gia von - gia tri hang huy) 90 ngay.
  A = nhom tao 80% loi nhuan, B = 15% tiep theo, C = phan con lai (ke ca SKU lo).
- XYZ: he so bien thien (CV) cua nhu cau theo tuan. X < 0.5 (on dinh), Y 0.5-1, Z > 1 (that thuong).

Ma tran 9 o quyet dinh muc ton an toan (z) va lam co so de xuat ngung nhap.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

Z_BY_CLASS = {
    "AX": 2.05, "AY": 1.65, "AZ": 1.28,
    "BX": 1.65, "BY": 1.28, "BZ": 1.04,
    "CX": 1.28, "CY": 1.04, "CZ": 0.84,
}

POLICY_BY_CLASS = {
    "AX": "Hàng chủ lực ổn định: tồn an toàn cao (~98%), đặt đều theo lịch.",
    "AY": "Chủ lực, dao động: theo dõi sát mùa vụ/khuyến mãi, tồn an toàn ~95%.",
    "AZ": "Chủ lực nhưng thất thường: đặt theo sự kiện, SM nên xem từng đơn.",
    "BX": "Ổn định, lợi nhuận vừa: tự động hóa đặt hàng được.",
    "BY": "Trung bình: đặt theo dự báo, tồn an toàn ~90%.",
    "BZ": "Trung bình, thất thường: giảm tồn, chấp nhận hết hàng thỉnh thoảng.",
    "CX": "Lợi nhuận thấp nhưng ổn định: giữ tồn tối thiểu.",
    "CY": "Lợi nhuận thấp, dao động: ứng viên thu hẹp danh mục.",
    "CZ": "Lợi nhuận thấp, thất thường: ứng viên ngừng nhập (nếu không phải hàng kéo khách).",
}


@dataclass
class SkuStats:
    sku: str
    name: str
    gross_margin_after_waste: float
    weekly_demand: list[float]
    waste_rate: float = 0.0  # gia tri huy / (gia von ban + gia tri huy)
    is_traffic_driver: bool = False
    substitutes: list[str] = field(default_factory=list)


@dataclass
class SkuClass:
    sku: str
    abc: str
    xyz: str
    cv: float | None
    margin: float
    margin_share: float

    @property
    def cell(self) -> str:
        return self.abc + self.xyz


def coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    if m <= 0:
        return None
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var) / m


def classify(stats: list[SkuStats], a_cut: float = 0.80, b_cut: float = 0.95,
             x_cv: float = 0.5, y_cv: float = 1.0) -> dict[str, SkuClass]:
    total_pos = sum(max(0.0, s.gross_margin_after_waste) for s in stats) or 1.0
    ordered = sorted(stats, key=lambda s: s.gross_margin_after_waste, reverse=True)
    out: dict[str, SkuClass] = {}
    cum = 0.0
    for s in ordered:
        m = s.gross_margin_after_waste
        share = max(0.0, m) / total_pos
        prev = cum
        cum += share
        if m <= 0:
            abc = "C"
        elif prev < a_cut:
            abc = "A"
        elif prev < b_cut:
            abc = "B"
        else:
            abc = "C"
        cv = coefficient_of_variation(s.weekly_demand)
        if cv is None:
            xyz = "Z"
        elif cv < x_cv:
            xyz = "X"
        elif cv <= y_cv:
            xyz = "Y"
        else:
            xyz = "Z"
        out[s.sku] = SkuClass(s.sku, abc, xyz, None if cv is None else round(cv, 3), m, round(share, 5))
    return out


def delist_candidates(stats: list[SkuStats], classes: dict[str, SkuClass],
                      waste_threshold: float = 0.15) -> list[dict]:
    """Ung vien ngung nhap: o CY/CZ, khong phai hang keo khach, va (huy nhieu hoac lo)."""
    res = []
    for s in stats:
        c = classes[s.sku]
        if c.abc != "C" or c.xyz == "X":
            continue
        if s.is_traffic_driver:
            continue
        reasons = [f"Nhóm {c.cell}: {POLICY_BY_CLASS[c.cell]}"]
        score = 1.0 if c.xyz == "Z" else 0.5
        if s.waste_rate >= waste_threshold:
            reasons.append(f"Tỷ lệ hủy {s.waste_rate:.0%} (ngưỡng {waste_threshold:.0%}).")
            score += s.waste_rate * 2
        if s.gross_margin_after_waste <= 0:
            reasons.append("Lợi nhuận gộp sau hủy ≤ 0 trong 90 ngày.")
            score += 1.0
        if len(reasons) == 1:
            continue  # chi la C-Y/C-Z ma khong huy nhieu / khong lo -> chua de xuat
        if s.substitutes:
            reasons.append(f"Có hàng thay thế: {', '.join(s.substitutes[:3])}.")
            score += 0.5
        else:
            reasons.append("Không có hàng thay thế: cân nhắc giảm tồn thay vì ngừng hẳn.")
        res.append({"sku": s.sku, "name": s.name, "cell": c.cell, "score": round(score, 2),
                    "margin_90d": round(s.gross_margin_after_waste), "waste_rate": round(s.waste_rate, 3),
                    "has_substitute": bool(s.substitutes), "reasons": reasons})
    return sorted(res, key=lambda r: r["score"], reverse=True)
