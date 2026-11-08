"""Migrate schema bang Alembic; bootstrap cho container (migrate + seed neu DB trong)."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from app.db import Base, SessionLocal, engine

BACKEND = Path(__file__).resolve().parent.parent


def migrate() -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def reset() -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def bootstrap() -> None:
    migrate()
    from app.models import Product

    db = SessionLocal()
    try:
        empty = db.scalar(select(Product.id).limit(1)) is None
    finally:
        db.close()
    if empty:
        from app.sim.seed import seed

        print("DB trống, đang sinh dữ liệu giả lập 365 ngày...", seed())


if __name__ == "__main__":
    bootstrap()
