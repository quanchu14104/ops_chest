"""Phat hien thoi quen sua so luong cua Store Manager. Thuan tat dinh, khong doc DB.

Chi coi la "thoi quen" khi du nhieu lan sua, tren nhieu don, va cung chieu: mot lan SM giam don vi co
ly do rieng khong phai la tin hieu de doi cach tinh.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

MIN_EDITS = 5
MIN_PROPOSALS = 3
MIN_GAP = 0.15
MIN_CONSISTENCY = 0.7
FACTOR_RANGE = (0.5, 1.5)


@dataclass(frozen=True)
class EditObservation:
    category: str
    proposal_id: int
    ratio: float  # so SM chot / so he thong de xuat


def suggested_factor(med: float) -> float:
    """Lam tron toi 0,05 de de doc va khong gia vo chinh xac."""
    return round(max(FACTOR_RANGE[0], min(FACTOR_RANGE[1], round(med * 20) / 20)), 2)


def detect_patterns(obs: list[EditObservation]) -> list[dict]:
    by_cat: dict[str, list[EditObservation]] = {}
    for o in obs:
        by_cat.setdefault(o.category, []).append(o)
    out = []
    for category, rows in by_cat.items():
        ratios = [r.ratio for r in rows]
        proposals = {r.proposal_id for r in rows}
        med = median(ratios)
        if len(rows) < MIN_EDITS or len(proposals) < MIN_PROPOSALS or abs(med - 1) < MIN_GAP:
            continue
        same_way = sum(1 for r in ratios if (r < 1) == (med < 1) and r != 1) / len(ratios)
        if same_way < MIN_CONSISTENCY:
            continue
        out.append({"category": category, "edits": len(rows), "proposals": len(proposals),
                    "median_ratio": round(med, 3), "consistency": round(same_way, 3),
                    "factor": suggested_factor(med)})
    return sorted(out, key=lambda p: -p["edits"])
