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
    """Gio hien tai. Khi co ngay co dinh (SIM_TODAY/test) thi giu gio that nhung dung NGAY co dinh,
    de han hieu luc cua de xuat (cuoi ngay `today()`) khong het han khi dong ho that di qua ngay do."""
    real = datetime.now(ZoneInfo(settings.timezone))
    fixed = _override if _override is not None else settings.sim_today
    return real.replace(year=fixed.year, month=fixed.month, day=fixed.day) if fixed else real


def set_today(d: date | None) -> None:
    """Dung cho test va nut tua nhanh demo (app.sim.advance)."""
    global _override
    _override = d


SIM_CLOCK_KEY = "sim_today"


def load_persisted() -> None:
    """Khoi dong lai server khong duoc lam mat ngay da tua nhanh."""
    from app.db import SessionLocal
    from app.models import AppMeta

    db = SessionLocal()
    try:
        row = db.get(AppMeta, SIM_CLOCK_KEY)
    except Exception:  # noqa: BLE001 - DB chua migrate: coi nhu chua tua
        return
    finally:
        db.close()
    if row:
        set_today(date.fromisoformat(row.value))
