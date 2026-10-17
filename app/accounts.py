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
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import permissions
from app.models import AccountEvent, Role, User
from app.security import (
    generate_pin,
    generate_temp_password,
    hash_password,
    validate_new_password,
    validate_pin,
    verify_password,
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

ACTION_LABELS = {
    "create_office": "운영자 계정 생성",
    "issue": "위원 계정 발급",
    "signup": "후원자 직접 가입",
    "register": "후원자 대신 등록",
    "reset": "비밀번호 초기화",
    "change_password": "비밀번호 변경",
    "change_pin": "숫자 4자리 변경",
    "locked": "연속 실패로 잠김",
    "unlocked": "매니저가 잠금 해제",
    "deactivate": "위촉 해제",
    "reactivate": "위촉 복구",
    "grant_manager": "매니저 권한 부여",
    "revoke_manager": "매니저 권한 해제",
    "approve_donor": "후원자 승인",
    "unapprove_donor": "후원자 승인 취소",
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


# --- 후원자 (위원회 결정, 안건 07) ----------------------------------------
#
# 후원자는 이메일 대신 휴대폰 번호로 로그인하고 비밀번호는 숫자 4자리다. "굉장히 단순해야
# 된다"는 결정이었고, 가게를 운영하면서 짧게 쓰는 앱이라 그 편이 맞다.
#
# 회의에서는 "자기 이름하고 숫자 4가지만 입력하면" 이라고 했지만 이름으로는 사람을 가릴 수
# 없다 — 같은 이름이 둘이면 누구 계정인지 정해지지 않는다. 입력 칸 수는 그대로 둔 채
# 휴대폰 번호를 쓴다. 초기화 규칙이 "전화번호 뒤 네 자리"인 것도 번호를 전제한다.

PHONE_DIGITS = (10, 11)


def normalize_phone(raw: str) -> str:
    """숫자만 남긴다. 사람은 010-1234-5678 로도, 01012345678 로도 적는다."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) not in PHONE_DIGITS or not digits.startswith("0"):
        raise AccountError("휴대폰 번호를 010-1234-5678 처럼 입력해 주세요.")
    return digits


def find_donor_by_phone(db: Session, raw_phone: str) -> User | None:
    return db.scalar(select(User).where(User.phone == normalize_phone(raw_phone)))


def _prepare_donor(db: Session, name: str, phone: str) -> tuple[str, str]:
    name = name.strip()
    if not name:
        raise AccountError("이름을 입력해 주세요.")
    digits = normalize_phone(phone)
    if db.scalar(select(User).where(User.phone == digits)) is not None:
        raise AccountError("이미 등록된 휴대폰 번호입니다. 그 번호로 로그인해 주세요.")
    return name, digits


def _new_donor(db: Session, name: str, phone: str, pin: str, *, must_change: bool) -> User:
    donor = User(
        name=name,
        phone=phone,
        role=Role.DONOR,
        password_hash=hash_password(pin),
        must_change_password=must_change,
    )
    db.add(donor)
    db.flush()
    return donor


def signup_donor(
    db: Session, *, name: str, phone: str, pin: str, confirm: str, shop_name: str = ""
) -> User:
    """후원자가 직접 가입한다. 숫자 4자리를 본인이 정하므로 전달할 것이 없다."""
    name, digits = _prepare_donor(db, name, phone)
    if pin != confirm:
        raise AccountError("숫자 4자리 두 칸이 서로 다릅니다.")
    problem = validate_pin(pin, phone=digits)
    if problem:
        raise AccountError(problem)

    donor = _new_donor(db, name, digits, pin, must_change=False)
    _attach_shop(db, donor, shop_name)
    log_event(db, donor, "signup", donor, "후원자 직접 가입")
    db.commit()
    return donor


def register_donor(
    db: Session, actor: User, *, name: str, phone: str, shop_name: str = ""
) -> tuple[User, str]:
    """운영자나 위원이 후원자를 대신 등록한다.

    "후원하시는 분이 연세가 있으시고 (가입을) 어려워할 수도 있으니까" 대신 만들어 드린다.
    이때는 숫자 4자리를 앱이 만들어 화면에 한 번 보여 주고, 후원자는 첫 로그인에서 바꾼다.
    """
    name, digits = _prepare_donor(db, name, phone)
    pin = generate_pin()
    donor = _new_donor(db, name, digits, pin, must_change=True)
    _attach_shop(db, donor, shop_name)
    log_event(db, donor, "register", actor, f"{actor.role.tag}가 대신 등록")
    db.commit()
    return donor, pin


def reset_donor_pin(db: Session, actor: User, donor: User) -> str:
    """전화번호 뒤 네 자리로 초기화한다 (위원회 결정).

    후원자가 이미 아는 값이라 따로 전할 것이 없다. 다만 번호를 아는 사람은 누구나 짐작할 수
    있는 값이므로, 첫 로그인에서 반드시 바꾸게 한다.
    """
    if donor.role is not Role.DONOR:
        raise AccountError("후원자 계정만 이렇게 초기화합니다.")
    if not donor.phone:
        raise AccountError("휴대폰 번호가 없는 계정은 초기화할 수 없습니다.")

    pin = donor.phone[-4:]
    donor.password_hash = hash_password(pin)
    donor.must_change_password = True
    unlock(db, donor, commit=False)
    log_event(db, donor, "reset", actor, "전화번호 뒤 네 자리로 초기화")
    db.commit()
    return pin


def change_pin(db: Session, donor: User, *, current: str, new: str, confirm: str) -> None:
    if not verify_password(current, donor.password_hash):
        raise AccountError("지금 숫자 4자리가 맞지 않습니다.")
    if new != confirm:
        raise AccountError("새 숫자 4자리 두 칸이 서로 다릅니다.")
    if new == current:
        raise AccountError("지금과 다른 숫자로 정해 주세요.")
    problem = validate_pin(new, phone=donor.phone)
    if problem:
        raise AccountError(problem)

    donor.password_hash = hash_password(new)
    donor.must_change_password = False
    log_event(db, donor, "change_pin", donor)
    db.commit()


def _attach_shop(db: Session, donor: User, shop_name: str) -> None:
    name = (shop_name or "").strip()
    if not name:
        return
    from app.models import Shop

    db.add(Shop(owner_id=donor.id, name=name))


# --- 연속 실패 잠금 ---------------------------------------------------------
#
# 숫자 4자리는 1만 가지뿐이다. 하나씩 넣어 보면 뚫리므로 횟수를 세야 한다.
# 이메일 로그인에도 같이 적용한다 — 막을 이유는 같다.

MAX_FAILED_LOGINS = 5


def is_locked(user: User) -> bool:
    """잠금은 시간이 지나 풀리지 않는다. 매니저가 해제한다 (위원회 결정, 안건 15)."""
    return user.locked_at is not None


def record_failure(db: Session, user: User) -> int:
    """실패를 세고, 한도를 넘으면 잠근다. 남은 시도 횟수를 돌려준다."""
    user.failed_logins = (user.failed_logins or 0) + 1
    if user.failed_logins >= MAX_FAILED_LOGINS:
        user.locked_at = datetime.now(timezone.utc)
        user.failed_logins = 0
        log_event(db, user, "locked", None, f"{MAX_FAILED_LOGINS}회 연속 실패")
        db.commit()
        return 0
    db.commit()
    return MAX_FAILED_LOGINS - user.failed_logins


def unlock(db: Session, user: User, commit: bool = True) -> None:
    """실패 횟수와 잠금을 함께 지운다. 로그인 성공과 초기화에서 쓴다."""
    user.failed_logins = 0
    user.locked_at = None
    if commit:
        db.commit()


def unlock_by_manager(db: Session, manager: User, target: User) -> User:
    """매니저가 잠금을 해제한다.

    잠긴 사람은 운영팀에 연락해야 한다. 그 연락처를 로그인 화면에 띄우는 것이 같은 안건의
    나머지 절반이다 — 연락할 곳을 모르면 잠금을 풀 길이 없다.
    """
    if not permissions.is_manager(manager):
        raise AccountError("잠금 해제는 매니저 권한이 있는 위원만 할 수 있습니다.")
    if not is_locked(target):
        raise AccountError(f"{target.name}님의 계정은 잠겨 있지 않습니다.")

    unlock(db, target, commit=False)
    log_event(db, target, "unlocked", manager)
    db.commit()
    return target


def locked_accounts(db: Session) -> list[User]:
    """잠긴 계정 — 매니저 화면에 띄운다."""
    return list(
        db.scalars(select(User).where(User.locked_at.is_not(None)).order_by(User.locked_at)).all()
    )


def approve_donor(db: Session, manager: User, donor: User) -> User:
    """후원자를 승인한다 — 매니저만 (위원회 결정, 안건 10·14).

    거르는 대상은 물건이 아니라 사람이다. 한 번 승인하면 그 후원자가 올리는 나눔글 전체가
    위원의 매칭 후보에 오른다. 그래서 승인은 현장을 본 사람의 판단이어야 한다.
    """
    if not permissions.is_manager(manager):
        raise AccountError("후원자 승인은 매니저 권한이 있는 위원만 할 수 있습니다.")
    if donor.role is not Role.DONOR:
        raise AccountError("후원자 계정만 승인합니다.")
    if donor.approved_at is not None:
        raise AccountError(f"{donor.name}님은 이미 승인되어 있습니다.")

    donor.approved_at = datetime.now(timezone.utc)
    donor.approved_by_id = manager.id
    log_event(db, donor, "approve_donor", manager)
    db.commit()
    return donor


def unapprove_donor(db: Session, manager: User, donor: User, reason: str) -> User:
    """승인을 되돌린다.

    가게가 문을 닫거나 문제가 생겼을 때 쓴다. 되돌리면 그 후원자의 나눔글은 위원의 후보에서
    빠지지만, 이미 매칭된 건은 그대로 둔다 — 받는 가정에게는 이미 약속된 것이다.
    """
    if not permissions.is_manager(manager):
        raise AccountError("후원자 승인 취소는 매니저 권한이 있는 위원만 할 수 있습니다.")
    if donor.role is not Role.DONOR:
        raise AccountError("후원자 계정만 다룹니다.")
    if not reason.strip():
        raise AccountError("승인을 취소하는 이유를 적어 주세요.")

    donor.approved_at = None
    donor.approved_by_id = None
    log_event(db, donor, "unapprove_donor", manager, reason.strip())
    db.commit()
    return donor
