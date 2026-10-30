"""협의체 개설과 승인 — 슈퍼 관리자가 하는 일.

협의체를 두 걸음으로 만든다: 등록하고, 그다음에 승인한다.

한 걸음으로 끝내지 않는 이유는 '만들어졌다'와 '열렸다'가 다른 사건이기 때문이다. 등록은
행정 절차고, 승인은 그 동 주민이 전용 주소로 들어와 가입할 수 있게 되는 순간이다. 사이에
첫 관리자를 정하고 담당 위원을 채우는 준비가 들어간다. 한 걸음으로 묶으면 준비가 끝나기
전에 주소가 살아 있고, 그 주소로 들어온 주민의 전화번호가 아무도 보지 않는 화면에 쌓인다.

슈퍼 관리자가 할 수 있는 일은 여기까지다. 협의체를 만들고 첫 관리자를 세우고 열어 주는
것까지. 그 안의 케이스·식별정보·매칭은 그 협의체 사람들의 것이고, 슈퍼 관리자의 화면에
오지 않는다 (app/permissions.py 의 _SUPER_NEVER).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Council, Role, User

# 전용 주소에 들어가는 조각이라 영소문자·숫자·하이픈만 받는다. 한글 동 이름을 그대로 쓰면
# 주소가 퍼센트 인코딩으로 길어져, 카톡으로 보내고 받아 적기 어려워진다.
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")

# 주소를 선점하거나 시스템 경로와 겹치는 슬러그를 막는다.
RESERVED_SLUGS = {
    "admin", "super", "office", "member", "donor", "login", "logout", "signup",
    "account", "static", "api", "health", "c", "www", "ium",
}


class CouncilError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 문장을 담는다."""


def _clean(value: str | None, field: str, limit: int) -> str:
    text = (value or "").strip()
    if not text:
        raise CouncilError(f"{field}을 입력해 주세요.")
    if len(text) > limit:
        raise CouncilError(f"{field}은 {limit}자까지 입력할 수 있습니다.")
    return text


def validate_slug(db: Session, raw: str | None) -> str:
    slug = (raw or "").strip().lower()
    if not slug:
        raise CouncilError("전용 주소를 입력해 주세요.")
    if not SLUG_RE.match(slug):
        raise CouncilError(
            "전용 주소는 영소문자로 시작하고 영소문자·숫자·하이픈만 써서 3~40자로 지어 주세요."
        )
    if slug in RESERVED_SLUGS:
        raise CouncilError(f"'{slug}' 는 쓸 수 없는 주소입니다. 다른 이름을 지어 주세요.")
    if db.scalar(select(Council).where(Council.slug == slug)) is not None:
        raise CouncilError(f"'{slug}' 주소는 이미 다른 협의체가 쓰고 있습니다.")
    return slug


def register(
    db: Session,
    actor: User,
    *,
    region: str,
    dong: str,
    slug: str,
    region_code: str | None = None,
) -> Council:
    """협의체를 등록한다. 승인 전이므로 아직 전용 주소는 열리지 않는다."""
    if actor.role is not Role.SUPER:
        raise CouncilError("협의체 개설은 슈퍼 관리자만 할 수 있습니다.")

    region = _clean(region, "시·군·구", 60)
    dong = _clean(dong, "동 이름", 40)
    slug = validate_slug(db, slug)

    # 같은 동을 두 번 등록하면 어느 쪽이 '그 동'인지 알 수 없어진다. 자료가 둘로 갈린
    # 다음에 합치는 일은 식별정보까지 걸려 있어 간단하지 않다.
    duplicate = db.scalar(
        select(Council).where(
            func.lower(Council.region) == region.lower(),
            func.lower(Council.dong) == dong.lower(),
        )
    )
    if duplicate is not None:
        raise CouncilError(f"{duplicate.label} 협의체가 이미 등록돼 있습니다.")

    council = Council(
        region=region,
        dong=dong,
        slug=slug,
        region_code=(region_code or "").strip() or None,
    )
    db.add(council)
    db.commit()
    db.refresh(council)
    return council


def approve(db: Session, actor: User, council: Council) -> Council:
    """전용 주소를 연다.

    관리자(매니저) 없이는 열지 않는다. 열고 나면 주민이 가입할 수 있고, 가입한 후원자를
    승인할 사람이 그 협의체에 있어야 한다 (안건 10·14). 아무도 없으면 가입만 쌓인다.
    """
    if actor.role is not Role.SUPER:
        raise CouncilError("협의체 승인은 슈퍼 관리자만 할 수 있습니다.")
    if council.is_approved:
        raise CouncilError(f"{council.label} 협의체는 이미 승인돼 있습니다.")
    if manager_of(db, council) is None:
        raise CouncilError(
            f"{council.label} 협의체의 관리자를 먼저 발급해 주세요. "
            "가입한 후원자를 승인할 사람이 없으면 가입만 쌓입니다."
        )

    council.approved_at = datetime.now(timezone.utc)
    council.approved_by_id = actor.id
    council.is_active = True
    db.commit()
    db.refresh(council)
    return council


def suspend(db: Session, actor: User, council: Council, reason: str) -> Council:
    """협의체를 멈춘다 — 자료는 지우지 않는다.

    파기와 구분한다. 파일럿이 끝났거나 담당자가 없어 운영이 멈춘 협의체의 주소를 닫는
    일이고, 그 안의 기록은 보관 기간(안건 09)이 끝날 때까지 그대로 남는다. 멈춘 협의체는
    로그인도 조회도 되지 않으므로, 식별정보를 읽을 수 있는 사람도 사라진다.
    """
    if actor.role is not Role.SUPER:
        raise CouncilError("협의체 중지는 슈퍼 관리자만 할 수 있습니다.")
    if not (reason or "").strip():
        raise CouncilError("중지 사유를 적어 주세요. 되돌릴 때 근거가 됩니다.")

    council.is_active = False
    db.commit()
    db.refresh(council)
    return council


def resume(db: Session, actor: User, council: Council) -> Council:
    if actor.role is not Role.SUPER:
        raise CouncilError("협의체 재개는 슈퍼 관리자만 할 수 있습니다.")
    council.is_active = True
    db.commit()
    db.refresh(council)
    return council


def manager_of(db: Session, council: Council) -> User | None:
    """협의체의 관리자(매니저). 협의체당 한 사람이다 (2026-10-24 결정)."""
    return db.scalar(
        select(User).where(
            User.council_id == council.id,
            User.role == Role.MEMBER,
            User.is_manager.is_(True),
            User.is_active.is_(True),
        )
    )


def replace_manager(db: Session, actor: User, council: Council, successor: User) -> User:
    """관리자를 교체한다 — 슈퍼 관리자 쪽 길.

    관리자가 갑자기 연락이 안 될 때를 위한 길이다. 관리자 본인이 넘기는 길
    (/manage/members/<id>/manager)만 두면 그 상황에서 협의체가 멈추고, 이 길만 두면
    위원들이 스스로 정할 수 없다. 그래서 둘 다 둔다 (2026-10-24 결정).
    """
    from app import accounts

    if actor.role is not Role.SUPER:
        raise CouncilError("관리자 교체는 슈퍼 관리자만 할 수 있습니다.")
    if successor.council_id != council.id or successor.role is not Role.MEMBER:
        raise CouncilError("그 협의체의 위원만 관리자가 될 수 있습니다.")
    if not successor.is_active:
        raise CouncilError(f"{successor.name} 위원은 위촉이 해제된 상태입니다.")
    if not successor.is_approved:
        raise CouncilError(f"{successor.name} 위원을 먼저 승인해 주세요.")

    previous = manager_of(db, council)
    if previous is not None and previous.id == successor.id:
        raise CouncilError(f"{successor.name} 위원이 이미 관리자입니다.")

    if previous is not None:
        previous.is_manager = False
        accounts.log_event(
            db, previous, "revoke_manager", actor, f"{successor.name} 위원으로 교체"
        )
    successor.is_manager = True
    accounts.log_event(db, successor, "grant_manager", actor, "슈퍼 관리자가 교체")
    db.commit()
    db.refresh(successor)
    return successor


def members_of(db: Session, council: Council) -> list[User]:
    """협의체의 승인된 위원 — 관리자를 고를 후보다.

    슈퍼 관리자가 보는 유일한 '사람 목록' 이다. 이름과 이메일뿐이고, 그 위원이 어느
    가정을 맡고 있는지는 오지 않는다.
    """
    return list(
        db.scalars(
            select(User)
            .where(
                User.council_id == council.id,
                User.role == Role.MEMBER,
                User.is_active.is_(True),
                User.approved_at.is_not(None),
            )
            .order_by(User.name)
        ).all()
    )


def all_councils(db: Session) -> list[Council]:
    """승인 대기가 위로. 할 일이 있는 협의체가 먼저 보여야 한다."""
    return list(
        db.scalars(
            select(Council).order_by(
                Council.approved_at.is_not(None), Council.region, Council.dong
            )
        ).all()
    )


def counts_for(db: Session, council: Council) -> dict[str, int]:
    """협의체 규모 — 사람 수만 센다.

    케이스나 식별정보는 세지 않는다. '몇 가정을 돕고 있나' 는 그 협의체의 운영 상황이고,
    슈퍼 관리자가 알아야 할 일이 아니다. 여기서 숫자 하나를 더 보여 주고 싶은 유혹이
    생기면 app/permissions.py 의 _SUPER_NEVER 를 먼저 읽을 것.
    """
    return {
        "members": db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.council_id == council.id, User.role == Role.MEMBER, User.is_active)
        )
        or 0,
        "donors": db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.council_id == council.id, User.role == Role.DONOR)
        )
        or 0,
    }
