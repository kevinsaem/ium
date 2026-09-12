from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

# 설정은 app 모듈이 import 되기 전에 잡아야 한다.
# 파일 기반 임시 DB를 쓰는 이유: 테스트가 실제 Alembic 마이그레이션을 거친 스키마 위에서
# 돌게 하기 위해서다. create_all 로 만든 스키마를 검증하면 마이그레이션 누락을 놓친다.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="ium-test-"))
_DB_PATH = _TMP_DIR / "test.db"
os.environ["IUM_DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ.setdefault("IUM_SECRET_KEY", "test-secret")
os.environ.setdefault("IUM_MATCH_APPROVAL_MODE", "committee")
# 셸에 IUM_ENV=production 이 남아 있어도 테스트는 개발 모드로 돈다. 운영 모드는 test_production.py 가 따로 띄운다.
os.environ["IUM_ENV"] = "development"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import identity_service  # noqa: E402
from app.db import SessionLocal, engine, get_db, upgrade_to_head  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Case,
    DeliveryMethod,
    Offer,
    OfferKind,
    Role,
    Shop,
    User,
)
from app.security import hash_password  # noqa: E402

CASES = [
    ("선부3동 A가정", "식료품 시급", "가장 실직 · 4인 가족", True, "홍길동", "010-0000-0001"),
    ("선부3동 B가정", "집수리 필요", "교통사고 후 거동 불편", False, "김철수", "010-0000-0002"),
    ("선부3동 C어르신", "겨울 이불", "독거 어르신", False, "이영희", "010-0000-0003"),
]


@pytest.fixture(scope="session", autouse=True)
def migrated_db() -> Iterator[None]:
    upgrade_to_head()
    yield
    engine.dispose()


@pytest.fixture()
def db(migrated_db) -> Iterator[Session]:
    """테스트마다 모든 테이블을 비워 격리한다.

    트랜잭션 롤백 방식(savepoint)을 쓰지 않는 이유: pysqlite 드라이버가 BEGIN 을
    암묵적으로 처리해서 SAVEPOINT 롤백이 새어 나간다. 드라이버 동작을 바꾸는 것보다
    지우는 쪽이 단순하고, 서비스 코드가 내부에서 commit() 해도 그대로 통한다.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(table.delete())


@pytest.fixture()
def seeded(db) -> dict[str, User]:
    office = User(
        email="office@ium.test", password_hash=hash_password("ium1234"),
        name="협의체 운영자", role=Role.OFFICE,
    )
    member1 = User(
        email="member1@ium.test", password_hash=hash_password("ium1234"),
        name="이관희 위원", role=Role.MEMBER,
    )
    member2 = User(
        email="member2@ium.test", password_hash=hash_password("ium1234"),
        name="정미영 위원", role=Role.MEMBER,
    )
    donor = User(
        email="blue@ium.test", password_hash=hash_password("ium1234"),
        name="최세탁", role=Role.DONOR,
    )
    db.add_all([office, member1, member2, donor])
    db.flush()

    shop = Shop(owner_id=donor.id, name="푸른세탁소", category="세탁", walk_minutes=6, is_certified=True)
    db.add(shop)
    db.flush()

    for i, (title, kind) in enumerate(
        [("이불 빨래 무료 세탁", OfferKind.SERVICE), ("쌀 10kg", OfferKind.GOODS),
         ("도시락 5개", OfferKind.MEAL), ("도어록 수리", OfferKind.REPAIR)]
    ):
        db.add(
            Offer(
                shop_id=shop.id, title=title, kind=kind, icon="bag",
                quantity_note=f"{i + 1}건", delivery=DeliveryMethod.MEMBER_PICKUP,
            )
        )

    for code, need, note, urgent, name, phone in CASES:
        case = Case(
            code=code, need_summary=need, situation_note=note,
            is_urgent=urgent, member_id=member1.id,
        )
        db.add(case)
        db.flush()
        identity_service.upsert_identity(
            db, case, member1, name=name, phone=phone,
            address="안산시 단원구 (테스트)", consult_note="테스트 상담 메모",
            consent_given=True,
        )
    db.commit()
    return {"office": office, "member1": member1, "member2": member2, "donor": donor}


@pytest.fixture()
def client(db) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def committee_mode(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "match_approval_mode", "committee")
    monkeypatch.setattr(config.settings, "committee_approvals", 2)


@pytest.fixture()
def member_mode(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "match_approval_mode", "member")
