"""협의체 경계 — 테넌트가 섞이지 않게 하는 한 통로.

선부3동의 나눔글이 선부2동 위원에게 보이면 안 된다. 그런데 "조회할 때 council_id 조건을
꼭 넣자" 는 약속으로 두면 언젠가 깨진다. 라우트가 수십 개로 늘고, 새로 들어온 사람이
기존 조회를 복사해 쓰고, 급한 수정에서 한 줄이 빠진다. 경계가 한 번 새면 그 사고는
"목록이 좀 이상하다" 가 아니라 다른 동 주민의 사정이 남의 화면에 뜨는 일이다.

그래서 조건을 손으로 쓰지 않고 이 모듈을 거친다. 조회는 scoped(), 개별 객체는
assert_same() 이다. 두 함수만 보면 경계가 어떻게 지켜지는지 전부 읽힌다.

범위를 Case·Shop 에만 두고 Offer·Match 는 조인으로 따라가게 할 수도 있었다. 그러지
않은 이유는 조인이 빠지기 쉽기 때문이다. 테이블마다 council_id 를 들고 있으면 경계
조건이 어느 조회에서든 한 줄로 끝나고, 빠뜨렸는지도 눈에 보인다. 대신 쓸 때 채워 넣을
책임이 생기므로, 만드는 자리에서 stamp() 를 쓴다.

주소에서 협의체를 어떻게 알아내는지(슬러그냐 서브도메인이냐)도 여기 한 곳에만 둔다.
2026-10-24 결정은 경로 슬러그(/c/sunbu3/...)다. 나중에 서브도메인으로 바꾸더라도
고칠 곳은 from_request() 하나다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from app.models import Council, Role, User
from app.models.council import DEFAULT_SLUG

if TYPE_CHECKING:
    pass

S = TypeVar("S", bound=Select)


class CouncilNotFound(HTTPException):
    def __init__(self, slug: str) -> None:
        super().__init__(404, f"'{slug}' 협의체를 찾을 수 없습니다.")


def by_slug(db: Session, slug: str, *, approved_only: bool = True) -> Council:
    """슬러그로 협의체를 찾는다.

    승인 전 협의체는 없는 것으로 다룬다 — 개설 신청만 해 두고 주소를 뿌려서 주민을
    받는 길을 막는다. 승인 심사 화면에서는 approved_only=False 로 부른다.
    """
    council = db.scalar(select(Council).where(Council.slug == slug))
    if council is None or not council.is_active:
        raise CouncilNotFound(slug)
    if approved_only and not council.is_approved:
        raise CouncilNotFound(slug)
    return council


def default(db: Session) -> Council:
    """파일럿 협의체. 아직 협의체를 고르는 화면이 없는 자리에서 쓴다."""
    return by_slug(db, DEFAULT_SLUG)


def from_request(request: Request, db: Session) -> Council | None:
    """주소에서 협의체를 읽는다.

    지금은 경로의 /c/<slug>/ 다. 슬러그가 없으면 None 을 돌려주고, 부르는 쪽이
    로그인한 사람의 소속으로 대신한다 — 위원은 자기 동 주소를 매번 치지 않는다.
    """
    slug = request.path_params.get("slug")
    if not slug:
        parts = request.url.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "c":
            slug = parts[1]
    return by_slug(db, slug) if slug else None


def council_id_of(user: User) -> int | None:
    """이 사람이 볼 수 있는 협의체 id. 슈퍼 관리자는 None (경계 없음)."""
    return None if user.role is Role.SUPER else user.council_id


def scoped(stmt: S, model, user: User) -> S:
    """조회에 협의체 조건을 건다.

    슈퍼 관리자만 조건 없이 통과한다. 그 외의 사람이 소속 없이(council_id 가 비어)
    들어오면 빈 결과가 아니라 403 이다 — 데이터가 없는 것과 경계가 깨진 것을 같은
    화면으로 보여 주면 잘못된 쪽을 눈치챌 수 없다.
    """
    if user.role is Role.SUPER:
        return stmt
    cid = user.council_id
    if cid is None:
        raise HTTPException(403, "소속 협의체가 없는 계정입니다.")
    return stmt.where(model.council_id == cid)


def assert_same(user: User, obj) -> None:
    """개별 객체가 이 사람의 협의체 것인지 확인한다.

    id 를 주소에 직접 넣어 들어오는 길(/member/cases/37)에는 목록의 조건이 걸리지
    않는다. 가져온 뒤 여기서 한 번 더 막는다. 404 가 아니라 403 인 건, 남의 동
    케이스 번호를 찍어 보며 존재 여부를 알아내는 걸 막을 이유가 파일럿 규모에선
    크지 않고, 경계 위반이 로그에 또렷이 남는 쪽이 낫기 때문이다.
    """
    if user.role is Role.SUPER:
        return
    if obj is None:
        return
    if getattr(obj, "council_id", None) != user.council_id:
        raise HTTPException(403, "다른 협의체의 자료입니다.")


def stamp(user: User, *objs) -> None:
    """새로 만드는 객체에 협의체를 찍는다. 만드는 자리에서 부른다."""
    cid = council_id_of(user)
    if cid is None:
        raise HTTPException(400, "협의체를 지정해야 합니다.")
    for obj in objs:
        obj.council_id = cid
