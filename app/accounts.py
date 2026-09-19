"""계정 발급과 비밀번호.

운영 모드에서는 seed.py 가 막혀 있으므로 계정은 여기서만 생긴다.

- 첫 운영자: 서버에서 `python -m app.create_office` — 비밀번호는 실행하는 사람이 직접 입력
- 위원: 운영자가 위촉하며 발급 → 임시 비밀번호 → 첫 로그인에서 반드시 변경
- 후원자: 위원회 안건 07 결정 전이라 아직 없다

임시 비밀번호는 발급 응답 한 번에만 실어 보낸다. 세션에 담으면 쿠키를 타고 브라우저에
남는다 — 식별정보 열람을 리다이렉트 대신 직접 렌더하게 바꾼 것과 같은 이유다.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountEvent, Role, User
from app.security import (
    generate_temp_password,
    hash_password,
    validate_new_password,
    verify_password,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ACTION_LABELS = {
    "create_office": "운영자 계정 생성",
    "issue": "위원 계정 발급",
    "reset": "비밀번호 초기화",
    "change_password": "비밀번호 변경",
    "deactivate": "위촉 해제",
    "reactivate": "위촉 복구",
}


class AccountError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 문장을 담는다."""


def normalize_email(raw: str) -> str:
    # 로그인은 이메일을 소문자로 찾는다. 저장도 소문자로 해야 대소문자만 다른 중복이 안 생긴다.
    email = raw.strip().lower()
    if not EMAIL_RE.match(email):
        raise AccountError("이메일 형식이 올바르지 않습니다.")
    return email


def log_event(
    db: Session, user: User, action: str, actor: User | None = None, note: str | None = None
) -> None:
    db.add(
        AccountEvent(
            user_id=user.id,
            actor_id=actor.id if actor else None,
            action=action,
            note=note[:200] if note else None,
        )
    )


def _prepare(db: Session, name: str, email: str) -> tuple[str, str]:
    name = name.strip()
    if not name:
        raise AccountError("이름을 입력해 주세요.")
    email = normalize_email(email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise AccountError(f"{email} 은(는) 이미 쓰고 있는 이메일입니다.")
    return name, email


def create_office(db: Session, *, name: str, email: str, password: str) -> User:
    """서버 명령으로 운영자를 만든다. 비밀번호를 본인이 정했으므로 변경을 강제하지 않는다."""
    name, email = _prepare(db, name, email)
    problem = validate_new_password(password, email=email)
    if problem:
        raise AccountError(problem)

    user = User(
        email=email,
        name=name,
        role=Role.OFFICE,
        password_hash=hash_password(password),
        must_change_password=False,
    )
    db.add(user)
    db.flush()
    log_event(db, user, "create_office", note="서버 명령으로 생성")
    db.commit()
    return user


def issue_member(
    db: Session, actor: User, *, name: str, email: str, note: str | None = None
) -> tuple[User, str]:
    """위원 계정을 발급하고 임시 비밀번호를 돌려준다. 이 값은 어디에도 저장하지 않는다."""
    name, email = _prepare(db, name, email)
    temp = generate_temp_password()
    user = User(
        email=email,
        name=name,
        role=Role.MEMBER,
        password_hash=hash_password(temp),
        must_change_password=True,
        appointed_note=note,
    )
    db.add(user)
    db.flush()
    log_event(db, user, "issue", actor, note)
    db.commit()
    return user, temp


def reset_password(db: Session, actor: User, target: User) -> str:
    """임시 비밀번호로 초기화한다. 운영자가 위원 계정에 들어갈 수 있는 유일한 길이라 기록을 남긴다."""
    temp = generate_temp_password()
    target.password_hash = hash_password(temp)
    target.must_change_password = True
    log_event(db, target, "reset", actor)
    db.commit()
    return temp


def change_password(db: Session, user: User, *, current: str, new: str, confirm: str) -> None:
    # 로그인한 상태여도 지금 비밀번호를 다시 묻는다. 열려 있는 화면을 누가 대신 쓰는 경우를 막는다.
    if not verify_password(current, user.password_hash):
        raise AccountError("지금 비밀번호가 맞지 않습니다.")
    if new != confirm:
        raise AccountError("새 비밀번호 두 칸이 서로 다릅니다.")
    if new == current:
        raise AccountError("지금과 다른 비밀번호를 정해 주세요.")
    problem = validate_new_password(new, email=user.email)
    if problem:
        raise AccountError(problem)

    user.password_hash = hash_password(new)
    user.must_change_password = False
    log_event(db, user, "change_password", user)
    db.commit()
