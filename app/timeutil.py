"""시간 — 저장은 UTC, 사람에게 보이는 시각과 '이번 달'은 한국 시간.

협의체 보고서의 '9월'은 한국 시간 9월이다. UTC 로 달을 자르면 9월 1일 새벽(한국)에
전달한 건이 8월 보고서로 들어간다.

SQLite 는 timezone=True 컬럼도 tzinfo 없는 datetime 으로 돌려준다. 저장되는 값은 모두
UTC 이므로 tzinfo 가 없으면 UTC 로 간주한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)


def current_month() -> tuple[int, int]:
    now = datetime.now(KST)
    return now.year, now.month


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def parse_month(raw: str | None) -> tuple[int, int]:
    """'2026-08' → (2026, 8). 비었거나 형식이 틀리면 이번 달 — 주소창 값으로 500 을 내지 않는다."""
    try:
        year, month = (int(part) for part in (raw or "").split("-"))
    except ValueError:
        return current_month()
    if 2000 <= year <= 2100 and 1 <= month <= 12:
        return year, month
    return current_month()


def month_label(year: int, month: int) -> str:
    return f"{year}년 {month}월"


def in_month(dt: datetime | None, year: int, month: int) -> bool:
    if dt is None:
        return False
    local = to_local(dt)
    return (local.year, local.month) == (year, month)


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """한국 시간 기준 그 달의 [시작, 끝) 을 UTC 로. DB 에서 기간을 자를 때 쓴다."""
    next_year, next_month = shift_month(year, month, 1)
    start = datetime(year, month, 1, tzinfo=KST)
    end = datetime(next_year, next_month, 1, tzinfo=KST)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def recent_months(count: int) -> list[tuple[str, str]]:
    """이번 달부터 거슬러 올라간 (값, 라벨) 목록. 기간 선택 상자용."""
    year, month = current_month()
    months = [shift_month(year, month, -i) for i in range(count)]
    return [(f"{y:04d}-{m:02d}", month_label(y, m)) for y, m in months]
