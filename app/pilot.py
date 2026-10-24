"""파일럿 성공 지표.

위원회 결정(2026-09-19, 안건 04):

- 기간은 1개월. 시작일은 앱이 완성된 뒤에 정하므로 운영자가 화면에서 넣는다.
- 매칭 건수는 한 숫자로 보지 않는다. 단계별로 센다.
- 위원 만족도·활동 위원 수는 지표에서 뺀다 ("위원 지표까지 필요 없을 것 같습니다").

2차 회의(안건 16)에서 목표 숫자를 미리 정하지 않기로 했다. "전달 완료 건을 기준으로
카운트해 위원들끼리 공유하고 성과 자료로 활용한다" — 그래서 목표 대비 달성률을 보여 주지
않고 건수만 센다. 10곳·20건 같은 숫자를 걸어 두면 숫자를 맞추는 일이 목적이 된다.

나눔글 건건이 심사하는 단계가 폐기됐으므로(안건 10) 단계는 이렇게 읽힌다.

    후원자 승인 -> 나눔글 접수 -> 위원 매칭 -> 전달 완료
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MatchStatus, Offer, Policy, Role, Shop, User
from app.timeutil import KST, shift_month, to_local

@dataclass
class Window:
    """지표를 세는 기간. 시작일이 없으면 전체 기간을 뜻한다."""

    start: date | None
    end: date | None
    months: int

    @property
    def is_set(self) -> bool:
        return self.start is not None

    def contains(self, moment: datetime | None) -> bool:
        if moment is None:
            return False
        if not self.is_set:
            return True
        day = to_local(moment).date()
        return self.start <= day <= self.end

    def days_left(self, today: date | None = None) -> int | None:
        if not self.is_set:
            return None
        return (self.end - (today or datetime.now(KST).date())).days

    @property
    def label(self) -> str:
        if not self.is_set:
            return f"기간 미설정 · 누적 집계 (예정 {self.months}개월)"
        return f"{self.start} ~ {self.end} ({self.months}개월)"


def window(policy: Policy) -> Window:
    start = policy.pilot_start
    if start is None:
        return Window(start=None, end=None, months=policy.pilot_months)
    year, month = shift_month(start.year, start.month, policy.pilot_months)
    day = start.day
    while day > 28:
        try:
            end = date(year, month, day)
            break
        except ValueError:
            day -= 1
    else:
        end = date(year, month, day)
    return Window(start=start, end=end, months=policy.pilot_months)


def funnel(db: Session, win: Window, viewer: User) -> dict[str, int]:
    """단계별 건수. 목표 대비가 아니라 건수 그대로 본다 (위원회 결정, 안건 16).

    지표는 협의체마다 따로 센다. 섞이면 "우리 동이 몇 건 했는지" 가 사라지고, 그 숫자를
    위원들끼리 공유해 성과 자료로 쓰자던 결정도 의미가 없어진다.
    """
    from app import tenancy

    offers = list(db.scalars(tenancy.scoped(select(Offer), Offer, viewer)).all())
    matches = list(db.scalars(tenancy.scoped(select(Match), Match, viewer)).all())
    donors = list(
        db.scalars(tenancy.scoped(select(User), User, viewer).where(User.role == Role.DONOR)).all()
    )

    posted = [o for o in offers if win.contains(o.created_at)]
    matched = [m for m in matches if win.contains(m.created_at)]
    return {
        # 승인된 후원자 — 거르는 대상이 물건에서 사람으로 바뀌었다 (안건 10)
        "donors_approved": len([d for d in donors if win.contains(d.approved_at)]),
        "donors_waiting": len([d for d in donors if d.approved_at is None]),
        "offers_posted": len(posted),
        "matched": len([m for m in matched if m.status is not MatchStatus.CANCELLED]),
        "cancelled": len([m for m in matched if m.status is MatchStatus.CANCELLED]),
        # 위원들이 함께 보는 성과 숫자
        "delivered": len(
            [m for m in matches if m.status is MatchStatus.DELIVERED and win.contains(m.delivered_at)]
        ),
        "certified_shops": len(
            [
                s
                for s in db.scalars(tenancy.scoped(select(Shop), Shop, viewer)).all()
                if s.is_certified
            ]
        ),
    }
