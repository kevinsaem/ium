from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, User


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


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


def require_role(*roles: Role) -> Callable[[User], User]:
    def _dep(user: User = Depends(current_user)) -> User:
        if user.must_change_password:
            raise PasswordChangeRequired()
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"{'/'.join(r.tag for r in roles)}만 접근할 수 있는 화면입니다.",
            )
        return user

    return _dep
