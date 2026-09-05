from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """테스트 전용. 실제 DB 스키마는 Alembic 마이그레이션이 관리한다."""
    from app import models  # noqa: F401  (모델 등록)
    from app.models.base import Base

    Base.metadata.create_all(engine)


def upgrade_to_head() -> None:
    """alembic upgrade head 와 같은 일을 파이썬에서 실행한다."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    command.upgrade(cfg, "head")


def is_migrated() -> bool:
    return inspect(engine).has_table("alembic_version")
