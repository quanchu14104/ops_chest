"""So sanh phuong an xu ly hang can date theo GIA TRI THU HOI KY VONG (VND) cua mot lo.

Phuong an: giu nguyen (de het han roi huy) / giam gia theo bac / tra NCC (neu thoa thuan cho phep).
Gia dinh co gian: giam p% gia -> nhu cau tang (elasticity * p). He so theo nhom vong doi, ghi ro
trong docs; Store Manager thay doi duoc.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ELASTICITY = {"FRESH": 3.0, "SHORT": 2.0, "LONG": 1.2}
ELASTICITY_SOURCE = {"FRESH": "giả định", "SHORT": "giả định", "LONG": "giả định"}


def _calibrate_from_frn() -> None:
    """Hang tuoi: thay gia dinh 3,0 bang uoc luong tren FreshRetailNet-50K (diem huan luyen, ngay con hang du gio,
    dang 'ban tang ~ 1 + e x muc giam'). FRN la giam gia khuyen mai, khong phai giam vi can han: chi la xap xi."""
    import json
    from pathlib import Path

    from app.config import settings

    if not settings.elasticity_from_frn:
        return
    p = Path(__file__).resolve().parents[1] / "sim" / "data" / "frn" / "elasticity.json"
    if not p.exists():
        return
    try:
        e = json.loads(p.read_text(encoding="utf-8"))["engine"]["all"]["e"]
    except (KeyError, ValueError, TypeError):
        return
    if e and e > 0:
        ELASTICITY["FRESH"] = round(float(e), 2)
        ELASTICITY_SOURCE["FRESH"] = "ước lượng trên FreshRetailNet-50K"


_calibrate_from_frn()
DISPOSAL_COST_PER_UNIT = 500  # VND: chi phi xu ly/huy uoc tinh moi don vi
EVENING_SHARE = 0.3  # mac dinh: ty trong luot khach sau 18h; giam gia gio vang chi ap cho phan con du
# Khung ban trong ngay: sang 6-11h, trua 11-14h, chieu 14-17h, toi 17-22h (cua hang dong cua 22h)
DAYPARTS = ((6, 11), (11, 14), (14, 17), (17, 22))
DEFAULT_DAYPART_SHARES = (0.2, 0.2, 0.225, 0.375)  # sau 18h = 0,3 nhu gia dinh cu


def share_after(shares, hour: int) -> float:
    """Ty trong nhu cau trong ngay con lai TU `hour` (phan bo deu trong moi khung)."""
    total = 0.0
    for (a, b), s in zip(DAYPARTS, shares):
        if hour <= a:
            total += s
        elif hour < b:
            total += s * (b - hour) / (b - a)
    return total


def peak_end_hour(shares) -> int:
    """Gio giam gia: ngay sau khung ban dinh cua nhom (com hop: sau trua; banh mi: sau sang), som nhat 11h."""
    i = max(range(len(shares)), key=lambda k: shares[k])
    return max(11, DAYPARTS[i][1]) if i < len(DAYPARTS) - 1 else 18


@dataclass
class DispositionInput:
    qty: float
    unit_cost: float
    unit_price: float
    days_left: int
    expected_sold_full_price: float
    elasticity: float
    accepts_return: bool = False
    return_min_days_before_expiry: int = 0
    return_credit_pct: float = 0.0
    disposal_cost_per_unit: float = DISPOSAL_COST_PER_UNIT
    markdown_steps: tuple[float, ...] = (0.2, 0.3, 0.5)
    daily_demand: float | None = None  # nhu cau du bao ca ngay (de tinh gio vang)
    current_markdown: float = 0.0  # muc giam dang ap cho lo: chi xet muc sau hon, khong tang gia tro lai
    # So don vi khach toi von mua gia goc neu khong co gio vang. None = suy tu nhu cau ca ngay.
    evening_full_price_units: float | None = None
    # So ngay toi HSD in tren bao bi (dieu khoan tra NCC tinh theo HSD). None = bang days_left.
    days_to_expiry: int | None = None
    # Gio vang theo nhom hang: ty trong nhu cau con lai sau gio giam gia, va gio bat dau giam
    remaining_share: float = EVENING_SHARE
    markdown_hour: int = 18
    # Rang buoc giam gia theo nhom hang (cau hinh; can doi chieu quy dinh ve khuyen mai truoc khi dung that)
    markdown_allowed: bool = True
    max_markdown: float = 0.95


@dataclass
class Option:
    action: str  # KEEP / MARKDOWN / RETURN
    label: str
    markdown_pct: float
    units_sold: float
    units_returned: float
    units_wasted: float
    value: float  # tien thu ve tu lo: doanh thu + hoan tien - chi phi huy
    delta_vs_keep: float
    feasible: bool
    note: str = ""
    timing: str = "ALL_DAY"  # ALL_DAY / EVENING (gio vang, chi phan du cuoi ngay)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("units_sold", "units_returned", "units_wasted"):
            d[k] = round(d[k], 1)
        for k in ("value", "delta_vs_keep"):
            d[k] = int(round(d[k]))
        return d


def evaluate(inp: DispositionInput) -> list[Option]:
    q = float(inp.qty)
    price, disposal = inp.unit_price, inp.disposal_cost_per_unit
    sold_full = min(q, max(0.0, inp.expected_sold_full_price))
    waste_full = q - sold_full
    value_full = sold_full * price - waste_full * disposal
    last_day = inp.days_left <= 0
    day_demand = inp.daily_demand if inp.daily_demand is not None else sold_full
    share = inp.remaining_share
    evening_buyers = (inp.evening_full_price_units if inp.evening_full_price_units is not None
                      else min(sold_full, day_demand * share))

    def outcome(p: float) -> tuple[float, float]:
        """(so ban duoc, tien thu ve) neu ap muc giam p."""
        if p <= 0:
            return sold_full, value_full
        if last_day:
            # Truoc gio vang ban gia goc; sau do nguoi vao mua them, nhung khach von tra gia goc cung duoc giam
            extra = min(waste_full, day_demand * share * inp.elasticity * p)
            return sold_full + extra, value_full + extra * (price * (1 - p) + disposal) - evening_buyers * price * p
        sold = min(q, sold_full * (1 + inp.elasticity * p))
        return sold, sold * price * (1 - p) - (q - sold) * disposal

    p0 = inp.current_markdown
    sold_keep, keep_value = outcome(p0)
    waste_keep = q - sold_keep
    opts = [
        Option("KEEP", "Giữ nguyên giá" if p0 <= 0 else f"Giữ mức giảm {int(p0 * 100)}%", p0, sold_keep, 0.0, waste_keep,
               keep_value, 0.0, True, "Không làm gì, phần không bán được sẽ bị hủy."),
    ]
    for p in inp.markdown_steps:
        if p <= p0 or not inp.markdown_allowed or p > inp.max_markdown + 1e-9:
            continue
        sold, value = outcome(p)
        if last_day:
            opts.append(Option(
                "MARKDOWN", f"Giảm giá giờ vàng {int(p * 100)}% (từ {inp.markdown_hour}h)", p, sold, 0.0, q - sold, value,
                value - keep_value, True,
                f"Chỉ giảm giá phần còn dư sau {inp.markdown_hour}h (sau khung bán đỉnh của nhóm hàng). "
                "Đã trừ phần khách sau giờ này vốn sẽ trả giá gốc.",
                timing="EVENING",
            ))
        else:
            opts.append(Option(
                "MARKDOWN", f"Giảm giá {int(p * 100)}%", p, sold, 0.0, q - sold, value, value - keep_value, True,
                "Giảm giá cả phần lẽ ra bán được giá gốc (mất doanh thu) để đẩy phần dư.",
            ))
    to_expiry = inp.days_left if inp.days_to_expiry is None else inp.days_to_expiry
    can_return = inp.accepts_return and to_expiry >= inp.return_min_days_before_expiry
    ret_units = waste_keep
    ret_value = keep_value + ret_units * (disposal + inp.unit_cost * inp.return_credit_pct)  # khong con ton phi huy
    if can_return:
        note = f"Trả {ret_units:.0f} đơn vị dư cho NCC, hoàn {int(inp.return_credit_pct * 100)}% giá vốn."
    elif not inp.accepts_return:
        note = "NCC không nhận trả hàng cận date."
    else:
        note = f"Quá hạn trả: NCC chỉ nhận khi còn ≥ {inp.return_min_days_before_expiry} ngày."
    opts.append(Option("RETURN", "Trả nhà cung cấp", 0.0, sold_keep, ret_units, 0.0, ret_value,
                       ret_value - keep_value, can_return and ret_units > 0, note))
    feasible = sorted((o for o in opts if o.feasible), key=lambda o: o.value, reverse=True)
    return feasible + [o for o in opts if not o.feasible]


def best(inp: DispositionInput) -> Option:
    return evaluate(inp)[0]
