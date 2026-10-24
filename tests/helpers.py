"""테스트 보조 함수.

conftest.py 에 두지 않는 이유가 있다. conftest 는 import 되는 순간 임시 DB 디렉터리를
만들고 IUM_DATABASE_URL 을 잡는다. 테스트 모듈이 `from tests.conftest import ...` 로
가져오면 pytest 가 플러그인으로 올린 conftest 와 별개의 모듈이 한 번 더 로드돼, 임시
디렉터리가 두 개 생기고 환경변수가 나중 것으로 덮인다. 그러면 부모 프로세스의 엔진과
자식 프로세스(python -m app.purge_expired)가 서로 다른 DB 를 보게 된다.

그래서 여기엔 부수효과가 없는 함수만 둔다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Council
from app.models.council import DEFAULT_SLUG


def pilot_id(db: Session) -> int:
    """파일럿 협의체 id. 테스트가 직접 자료를 만들 때 소속을 찍는다.

    소속이 없으면 NOT NULL 로 막히는 게 정상이다 — 이 헬퍼는 그 전제를 테스트에서도
    지키기 위한 것이고, 기본값으로 메워 주는 장치가 아니다.
    """
    return db.scalar(select(Council.id).where(Council.slug == DEFAULT_SLUG))
