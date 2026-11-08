"""Du bao luong hang se bi huy cua tung lo: mo phong ban FEFO theo du bao nhu cau."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class LotInput:
    lot_id: int
    qty: float
    expiry: date


@dataclass
class LotRisk:
    lot_id: int
    qty: float
    expiry: date
    days_left: int
    expected_sold: float
    expected_waste: float


def bucket(days_left: int) -> str:
    if days_left <= 0:
        return "Hết hạn hôm nay"
    if days_left <= 3:
        return "1-3 ngày"
    if days_left <= 7:
        return "4-7 ngày"
    return "> 7 ngày"


def project_lots(lots: list[LotInput], forecast_from_today: list[float], today: date) -> list[LotRisk]:
    """forecast_from_today[0] la nhu cau cua chinh hom nay (quet buoi sang, chua ban)."""
    state = sorted(([l.lot_id, float(l.qty), l.expiry] for l in lots if l.qty > 0), key=lambda x: x[2])
    sold = {l[0]: 0.0 for l in state}
    waste = {l[0]: 0.0 for l in state}
    if not state:
        return []
    horizon = (max(l[2] for l in state) - today).days + 1
    for k in range(max(horizon, 0)):
        d = today + timedelta(days=k)
        if k < len(forecast_from_today):
            need = forecast_from_today[k]
        else:
            need = forecast_from_today[-1] if forecast_from_today else 0.0
        for lot in state:
            if need <= 0:
                break
            if lot[2] < d or lot[1] <= 0:
                continue
            take = min(lot[1], need)
            lot[1] -= take
            need -= take
            sold[lot[0]] += take
        for lot in state:
            if lot[2] <= d and lot[1] > 0:
                waste[lot[0]] += lot[1]
                lot[1] = 0
    out = []
    for l in lots:
        if l.qty <= 0:
            continue
        out.append(
            LotRisk(
                lot_id=l.lot_id,
                qty=l.qty,
                expiry=l.expiry,
                days_left=(l.expiry - today).days,
                expected_sold=round(sold[l.lot_id], 2),
                expected_waste=round(waste[l.lot_id], 2),
            )
        )
    return out
