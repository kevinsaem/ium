"""월간 활동 보고서.

위원 개인 보고서와 동 전체 보고서가 같은 계산을 쓴다. 보고서는 시청에 그대로 제출되는
문서라서, 무엇을 '당월'로 세는지가 화면마다 달라지면 안 된다.

입력은 비식별 Case·Match 뿐이다. 식별정보는 이 모듈에 들어올 길이 없다.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.models import Case, Match, MatchStatus
from app.timeutil import in_month, month_label, to_local

FOOTER = "※ 본 보고서는 비식별 코드만 사용하여 자동 생성되었습니다."


@dataclass
class MonthlyReport:
    year: int
    month: int
    summary: dict[str, int]
    delivered: list[Match]
    text: str
    member_rows: list[dict[str, object]] = field(default_factory=list)

    @property
    def period_label(self) -> str:
        return month_label(self.year, self.month)


def build_monthly_report(
    cases: Iterable[Case],
    matches: Iterable[Match],
    year: int,
    month: int,
    heading: Sequence[str],
    *,
    by_member: bool = False,
) -> MonthlyReport:
    """당월의 기준 — 케이스는 발굴일, 매칭은 제안일, 전달은 전달일. 모두 한국 시간."""
    matches = list(matches)
    new_cases = [c for c in cases if in_month(c.created_at, year, month)]
    proposed = [m for m in matches if in_month(m.created_at, year, month)]
    delivered = sorted(
        (
            m
            for m in matches
            if m.status is MatchStatus.DELIVERED and in_month(m.delivered_at, year, month)
        ),
        key=lambda m: to_local(m.delivered_at),
    )

    summary = {
        "cases": len(new_cases),
        "urgent": sum(1 for c in new_cases if c.is_urgent),
        "public_support": sum(1 for c in new_cases if c.public_support_linked),
        "matches": len(proposed),
        "delivered": len(delivered),
        "shops": len({m.offer.shop_id for m in delivered}),
    }

    lines = [
        f"보고 기간: {month_label(year, month)}",
        *heading,
        "",
        f"1. 당월 발굴 케이스 {summary['cases']}건 (긴급 {summary['urgent']}건)",
        f"2. 당월 매칭 제안 {summary['matches']}건, 당월 전달 완료 {summary['delivered']}건",
        f"3. 참여 나눔가게 {summary['shops']}곳",
        f"4. 당월 발굴 케이스 중 공적지원 연계 {summary['public_support']}건",
    ]

    member_rows: list[dict[str, object]] = []
    if by_member:
        tally: dict[int, dict[str, object]] = {}
        for c in new_cases:
            row = tally.setdefault(c.member_id, {"name": c.member.name, "cases": 0, "delivered": 0})
            row["cases"] += 1
        for m in delivered:
            owner = m.case.member
            row = tally.setdefault(owner.id, {"name": owner.name, "cases": 0, "delivered": 0})
            row["delivered"] += 1
        member_rows = sorted(tally.values(), key=lambda r: str(r["name"]))
        summary["active_members"] = len(member_rows)
        lines += ["", f"5. 당월 활동 위원 {len(member_rows)}명"]
        lines += [
            f"  - {r['name']}: 발굴 {r['cases']}건 · 전달 {r['delivered']}건" for r in member_rows
        ] or ["  - 없음"]

    lines += ["", "당월 전달 내역:"]
    lines += [
        f"  - {to_local(m.delivered_at):%m/%d} {m.case.code} / {m.case.need_summary}"
        f" ← {m.offer.title} ({m.offer.shop.name})"
        for m in delivered
    ] or ["  - 없음"]
    lines += ["", FOOTER]

    return MonthlyReport(
        year=year,
        month=month,
        summary=summary,
        delivered=delivered,
        text="\n".join(lines),
        member_rows=member_rows,
    )
