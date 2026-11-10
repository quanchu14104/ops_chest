from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import SessionLocal
from app.jobs.daily import run_closing, run_evening, run_morning

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _wrap(fn):
    def job():
        db = SessionLocal()
        try:
            fn(db)
        except Exception:  # noqa: BLE001
            log.exception("Job %s lỗi", fn.__name__)
            db.rollback()
        finally:
            db.close()
    return job


def start() -> None:
    global _scheduler
    if _scheduler or not settings.enable_scheduler:
        return
    _scheduler = BackgroundScheduler(timezone=settings.timezone)
    _scheduler.add_job(_wrap(run_morning), "cron", hour=6, minute=30, id="morning")
    _scheduler.add_job(_wrap(run_evening), "cron", hour=17, minute=0, id="evening")
    _scheduler.add_job(_wrap(run_closing), "cron", hour=settings.closing_hour, minute=0, id="closing")
    _scheduler.start()
    log.info("Scheduler started: 06:30 quét sáng, 17:00 giờ vàng, %sh rút kệ", settings.closing_hour)


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
