from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User
from app.permissions import is_manager


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    if not _council_is_open(user):
        # 협의체가 중지되면 그 안의 식별정보를 읽을 수 있는 사람도 사라져야 한다.
        # 로그인 시점에만 막으면 이미 들어와 있던 세션이 그대로 살아 있다.
        request.session.clear()
        return None
    return user


def _council_is_open(user: User) -> bool:
    """이 사람의 협의체가 열려 있는가.

    슈퍼 관리자는 협의체에 속하지 않으므로 항상 통과한다 — 협의체를 다시 열 수 있는
    사람이 협의체 상태 때문에 막히면 되돌릴 방법이 없어진다.
    """
    council = user.council
    return council is None or (council.is_active and council.is_approved)


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요합니다.",
            headers={"Location": "/login"},
        )
    return user


class PasswordChangeRequired(Exception):
    """임시 비밀번호로 들어온 사람은 비밀번호를 바꾸기 전까지 다른 화면을 쓸 수 없다."""


def _require_approved(user: User) -> None:
    """승인 대기 위원은 어느 화면도 열지 못한다.

    초대 코드로 들어온 위원은 계정이 서도 바로 쓸 수 없다. 코드가 새어 들어온 가입이면
    이 관문이 마지막 방어선이고, 위원 화면은 곧 식별정보 화면이다.

    후원자에게는 걸지 않는다. 두 승인이 막는 것이 다르다 — 위원 승인은 식별정보를 읽을
    수 있는 사람을 늘리고, 후원자 승인은 그 가게의 나눔이 위원의 매칭 후보에 오르게
    한다 (안건 10). 승인 전 후원자도 가게를 등록하고 나눔글을 올릴 수 있어야 하고,
    화면에서 "승인되면 위원에게 보입니다" 를 알려 준다. 올릴 수조차 없게 하면 승인을
    기다릴 이유가 사라진다.

    로그인 자체를 막지 않는 이유도 같은 쪽이다. 본인이 "가입이 됐는지 안 됐는지" 를
    확인할 길이 있어야 한다. 로그인은 되고 화면에서 대기 중임을 알려 준다.
    """
    if user.role is Role.MEMBER and not user.is_approved:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="관리자 승인을 기다리는 계정입니다. 승인되면 바로 쓰실 수 있습니다.",
        )


def require_manager(user: User = Depends(current_user)) -> User:
    """매니저만 들어오는 화면.

    매니저는 위원 중 한 명이다 (위원회 결정, 안건 14). 역할만 보고 통과시키면 모든 위원이
    후원자 승인과 잠금 해제를 하게 된다.
    """
    if user.must_change_password:
        raise PasswordChangeRequired()
    _require_approved(user)
    if not is_manager(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="매니저 권한이 있는 위원만 할 수 있습니다.",
        )
    return user


def require_role(*roles: Role) -> Callable[[User], User]:
    def _dep(user: User = Depends(current_user)) -> User:
        if user.must_change_password:
            raise PasswordChangeRequired()
        _require_approved(user)
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"{'/'.join(r.tag for r in roles)}만 접근할 수 있는 화면입니다.",
            )
        return user

    return _dep
