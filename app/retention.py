"""식별정보 보관 기한.

위원회 결정(2026-09-19, 안건 01): 케이스를 종결한 뒤 3개월까지 보관하고 그 뒤에 파기한다.
기간은 하드코딩하지 않고 운영자가 화면에서 바꾼다 (Policy.identity_retention_months).

파기 자체는 자동으로 하지 않는다. 되돌릴 수 없는 일이라 누가 언제 했는지가 기록에 남아야
하고, 담당 위원이 누르는 것이 기본이다. 다만 기한이 지나도 아무도 모르면 보관 기간은
의미가 없으므로, 운영자 화면에 기한과 초과 여부를 드러내고 서버에서 일괄 파기할 명령을
따로 둔다 (python -m app.purge_expired).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, CaseStatus, Policy, User
from app.models.policy import (
    DEFAULT_RETENTION_MONTHS,
    MAX_RETENTION_MONTHS,
    MIN_RETENTION_MONTHS,
)
from app.timeutil import KST, shift_month, to_local


class PolicyError(ValueError):
    """사람에게 그대로 보여 줄 수 있는 문장을 담는다."""


def current(db: Session) -> Policy:
    """정책 한 행을 돌려준다. 없으면 기본값으로 만든다."""
    policy = db.scalar(select(Policy).where(Policy.id == 1))
    if policy is None:
        policy = Policy(id=1, identity_retention_months=DEFAULT_RETENTION_MONTHS)
        db.add(policy)
        db.commit()
        db.refresh(policy)
    return policy


def update_retention(db: Session, actor: User, raw_months: str) -> Policy:
    """보관 기간을 바꾼다. 범위를 벗어나면 400 대신 읽을 수 있는 문장을 던진다."""
    text = (raw_months or "").strip()
    try:
        months = int(text)
    except ValueError:
        raise PolicyError("보관 기간은 숫자(개월)로 입력해 주세요.") from None
    if not MIN_RETENTION_MONTHS <= months <= MAX_RETENTION_MONTHS:
        raise PolicyError(
            f"보관 기간은 {MIN_RETENTION_MONTHS}개월에서 {MAX_RETENTION_MONTHS}개월 사이로 정해 주세요."
        )

    policy = current(db)
    policy.identity_retention_months = months
    policy.updated_by_id = actor.id
    db.commit()
    db.refresh(policy)
    return policy


def deadline(case: Case, months: int) -> date | None:
    """이 케이스의 식별정보 파기 기한. 종결되지 않았으면 기한이 없다."""
    if case.status is not CaseStatus.CLOSED or case.closed_at is None:
        return None
    closed = to_local(case.closed_at).date()
    year, month = shift_month(closed.year, closed.month, months)
    # 종결일이 31일이고 대상 월이 짧으면 그 달의 마지막 날로 맞춘다.
    day = closed.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


@dataclass
class RetentionStatus:
    """운영자·위원 화면에 그대로 뿌릴 수 있는 한 줄 요약."""

    case: Case
    deadline: date | None
    days_left: int | None  # 음수면 기한 초과

    @property
    def holds_identity(self) -> bool:
        return self.case.has_identity

    @property
    def is_overdue(self) -> bool:
        return self.holds_identity and self.days_left is not None and self.days_left < 0

    @property
    def label(self) -> str:
        if not self.holds_identity:
            return "파기 완료"
        if self.deadline is None:
            return "종결 후 기한 시작"
        if self.days_left is not None and self.days_left < 0:
            return f"파기 기한 {-self.days_left}일 초과"
        return f"파기 기한까지 {self.days_left}일"


def status_for(case: Case, months: int, today: date | None = None) -> RetentionStatus:
    today = today or datetime.now(KST).date()
    due = deadline(case, months)
    return RetentionStatus(
        case=case, deadline=due, days_left=(due - today).days if due else None
    )


def expired(db: Session, months: int, today: date | None = None) -> list[Case]:
    """기한이 지났는데 식별정보가 남아 있는 케이스."""
    today = today or datetime.now(KST).date()
    closed = db.scalars(select(Case).where(Case.status == CaseStatus.CLOSED)).all()
    return [
        c
        for c in closed
        if c.has_identity
        and (due := deadline(c, months)) is not None
        and due < today
    ]
