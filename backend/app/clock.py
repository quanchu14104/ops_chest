"""Mot nguon duy nhat cho 'hom nay' de demo/backtest co the co dinh ngay."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import settings

_override: date | None = None


def today() -> date:
    if _override is not None:
        return _override
    if settings.sim_today is not None:
        return settings.sim_today
    return datetime.now(ZoneInfo(settings.timezone)).date()


def now() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def set_today(d: date | None) -> None:
    """Chi dung cho test."""
    global _override
    _override = d
