"""Cau hinh theo nhom hang: rang buoc giam gia (N11) va gio giam gia theo khung ban (N10).

Muc tran giam gia va cac nhom cam khuyen mai la cau hinh do cua hang khai bao. Can doi chieu Nghi dinh
81/2018/ND-CP (va van ban sua doi, huong dan) truoc khi dung that; he thong khong khang dinh noi dung phap ly.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.disposition import DEFAULT_DAYPART_SHARES, share_after
from app.models import CategoryPolicy

DEFAULT = {"markdown_allowed": True, "max_markdown_pct": 0.5, "daypart_shares": list(DEFAULT_DAYPART_SHARES),
           "markdown_hour": 18}


class MarkdownPolicyError(Exception):
    pass


def by_category(db: Session) -> dict[str, dict]:
    out = {}
    for c in db.scalars(select(CategoryPolicy)):
        out[c.category] = {"markdown_allowed": c.markdown_allowed, "max_markdown_pct": c.max_markdown_pct,
                           "daypart_shares": c.daypart_shares or DEFAULT["daypart_shares"],
                           "markdown_hour": c.markdown_hour}
    return out


def for_category(pol: dict[str, dict], category: str) -> dict:
    p = pol.get(category, DEFAULT)
    return {**p, "remaining_share": share_after(p["daypart_shares"], p["markdown_hour"])}


def check_markdown(pol: dict, category: str, pct: float) -> None:
    p = for_category(pol, category)
    if not p["markdown_allowed"]:
        raise MarkdownPolicyError(f"Nhóm {category} không được giảm giá theo cấu hình của cửa hàng.")
    if pct > p["max_markdown_pct"] + 1e-9:
        raise MarkdownPolicyError(f"Mức giảm {pct:.0%} vượt trần {p['max_markdown_pct']:.0%} của nhóm {category}.")
