"""파일럿 성공 지표.

위원회 결정(2026-09-19, 안건 04):

- 기간은 1개월. 시작일은 앱이 완성된 뒤에 정하므로 운영자가 화면에서 넣는다.
- 매칭 건수는 한 숫자로 보지 않는다. "제안이 몇 건 있었고 승인된 게 몇 건이고 또 전달까지
  이루어진 게 몇 건이었는지" 를 모두 본다. 그래서 단계별로 센다.
- 위원 만족도·활동 위원 수는 지표에서 뺀다 ("위원 지표까지 필요 없을 것 같습니다").

안건 05 로 승인의 자리가 나눔글로 옮겨졌으므로, 단계는 이렇게 읽힌다.

    나눔글 접수 -> 노출 승인 -> 위원 매칭 -> 전달 완료
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MatchStatus, Offer, OfferStatus, Policy, Shop
from app.timeutil import KST, shift_month, to_local

# 목표값 — 위원회 초안 (인증가게 10곳 · 전달 20건)
GOALS = [
    {"key": "certified_shops", "label": "인증 나눔가게", "target": 10, "unit": "곳"},
    {"key": "delivered", "label": "전달 완료", "target": 20, "unit": "건"},
]


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


def funnel(db: Session, win: Window) -> dict[str, int]:
    """단계별 건수. 한 숫자로 뭉치지 않는 것이 이 안건의 요지다."""
    offers = list(db.scalars(select(Offer)).all())
    matches = list(db.scalars(select(Match)).all())

    posted = [o for o in offers if win.contains(o.created_at)]
    matched = [m for m in matches if win.contains(m.created_at)]
    return {
        # 접수된 나눔글 (거절된 것까지 포함 — 후원자가 손을 든 횟수다)
        "offers_posted": len(posted),
        # 그중 운영팀이 노출을 승인한 것
        "offers_approved": len(
            [o for o in posted if o.status is not OfferStatus.PENDING
             and o.status is not OfferStatus.REJECTED]
        ),
        "offers_rejected": len([o for o in posted if o.status is OfferStatus.REJECTED]),
        "matched": len([m for m in matched if m.status is not MatchStatus.CANCELLED]),
        "cancelled": len([m for m in matched if m.status is MatchStatus.CANCELLED]),
        "delivered": len(
            [m for m in matches if m.status is MatchStatus.DELIVERED and win.contains(m.delivered_at)]
        ),
        "certified_shops": len([s for s in db.scalars(select(Shop)).all() if s.is_certified]),
    }


def goals(counts: dict[str, int]) -> list[dict[str, object]]:
    return [{**g, "current": counts[g["key"]]} for g in GOALS]
