"""마이그레이션과 모델이 어긋나지 않는지 확인한다.

모델에 컬럼을 추가하고 `alembic revision --autogenerate` 를 깜빡하면,
로컬에서는 멀쩡히 돌다가 배포한 DB에서만 터진다. 그 간극을 여기서 잡는다.
"""
from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db import engine
from app.models import Base


def test_no_drift_between_models_and_migrations(migrated_db):
    """마이그레이션으로 만든 스키마 == 모델이 기술하는 스키마."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        diff = compare_metadata(context, Base.metadata)

    # alembic_version 은 Alembic 이 관리하는 테이블이라 모델에 없다. 제외한다.
    drift = [d for d in diff if "alembic_version" not in str(d)]

    assert not drift, (
        "모델과 마이그레이션이 어긋났습니다. 다음을 실행하세요:\n"
        "  alembic revision --autogenerate -m \"설명\"\n"
        f"차이: {drift}"
    )


def test_every_table_is_covered(migrated_db):
    """모델에 정의된 테이블이 실제 DB에 전부 만들어졌는지."""
    from sqlalchemy import inspect

    actual = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    missing = expected - actual
    assert not missing, f"마이그레이션에 빠진 테이블: {missing}"
