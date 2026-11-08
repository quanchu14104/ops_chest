"""So sanh phuong an xu ly hang can date theo GIA TRI THU HOI KY VONG (VND) cua mot lo.

Phuong an: giu nguyen (de het han roi huy) / giam gia theo bac / tra NCC (neu thoa thuan cho phep).
Gia dinh co gian: giam p% gia -> nhu cau tang (elasticity * p). He so theo nhom vong doi, ghi ro
trong docs; Store Manager thay doi duoc.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ELASTICITY = {"FRESH": 3.0, "SHORT": 2.0, "LONG": 1.2}
DISPOSAL_COST_PER_UNIT = 500  # VND: chi phi xu ly/huy uoc tinh moi don vi
EVENING_SHARE = 0.3  # ty trong luot khach sau 18h; giam gia gio vang chi ap cho phan con du


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
    sold_keep = min(q, max(0.0, inp.expected_sold_full_price))
    waste_keep = q - sold_keep
    keep_value = sold_keep * inp.unit_price - waste_keep * inp.disposal_cost_per_unit
    opts = [
        Option("KEEP", "Giữ nguyên giá", 0.0, sold_keep, 0.0, waste_keep, keep_value, 0.0, True,
               "Không làm gì, phần không bán được sẽ bị hủy."),
    ]
    for p in inp.markdown_steps:
        if inp.days_left <= 0:
            # Ngay cuoi: giam gia gio vang sau 18h, chi ap cho phan con du -> khong an mat doanh thu gia goc
            base = inp.daily_demand if inp.daily_demand is not None else sold_keep
            extra = min(waste_keep, base * EVENING_SHARE * inp.elasticity * p)
            sold = sold_keep + extra
            waste = q - sold
            value = keep_value + extra * (inp.unit_price * (1 - p) + inp.disposal_cost_per_unit)
            opts.append(Option(
                "MARKDOWN", f"Giảm giá giờ vàng {int(p * 100)}% (sau 18h)", p, sold, 0.0, waste, value,
                value - keep_value, True, "Chỉ giảm giá phần còn dư cuối ngày, ban ngày vẫn bán giá gốc.",
                timing="EVENING",
            ))
            continue
        demand = sold_keep * (1 + inp.elasticity * p)
        sold = min(q, demand)
        waste = q - sold
        value = sold * inp.unit_price * (1 - p) - waste * inp.disposal_cost_per_unit
        opts.append(Option(
            "MARKDOWN", f"Giảm giá {int(p * 100)}%", p, sold, 0.0, waste, value, value - keep_value, True,
            "Giảm giá cả phần lẽ ra bán được giá gốc (mất doanh thu) để đẩy phần dư.",
        ))
    can_return = inp.accepts_return and inp.days_left >= inp.return_min_days_before_expiry
    ret_units = waste_keep
    ret_value = sold_keep * inp.unit_price + ret_units * inp.unit_cost * inp.return_credit_pct
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
