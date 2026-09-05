"""매칭 승인 규칙 테스트.

승인 방식(위원 단독 / 협의체 공동)이 아직 위원회 미정 안건이므로,
두 모드가 모두 의도대로 도는지 여기서 고정해 둔다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import matching
from app.models import Case, CaseStatus, MatchStatus, Offer, OfferStatus


def _fresh_pair(db):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    return case, offer


def test_committee_mode_needs_two_approvals(db, seeded, committee_mode):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    # 제안 위원의 1표만으로는 확정되지 않는다
    assert match.status is MatchStatus.PROPOSED
    assert match.approval_count == 1

    matching.approve(db, match, seeded["member2"])
    assert match.status is MatchStatus.APPROVED
    assert match.approval_count == 2


def test_duplicate_approval_does_not_count_twice(db, seeded, committee_mode):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    matching.approve(db, match, seeded["member1"])
    matching.approve(db, match, seeded["member1"])

    assert match.approval_count == 1
    assert match.status is MatchStatus.PROPOSED


def test_member_mode_approves_immediately(db, seeded, member_mode):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    assert match.status is MatchStatus.APPROVED


def test_offer_is_reserved_then_closed(db, seeded, member_mode):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    assert offer.status is OfferStatus.RESERVED

    matching.mark_delivered(db, match, seeded["member1"], "전달 완료")
    assert offer.status is OfferStatus.CLOSED
    assert case.status is CaseStatus.RESOLVED


def test_cannot_double_book_an_offer(db, seeded, member_mode):
    case, offer = _fresh_pair(db)
    matching.propose(db, case, offer, seeded["member1"])

    other_case = db.scalar(select(Case).where(Case.id != case.id, Case.status == CaseStatus.OPEN))
    with pytest.raises(Exception) as exc:
        matching.propose(db, other_case, offer, seeded["member1"])
    assert "매칭 중이거나 종료" in str(exc.value)


def test_cannot_deliver_before_approval(db, seeded, committee_mode):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    with pytest.raises(Exception) as exc:
        matching.mark_delivered(db, match, seeded["member1"])
    assert "승인 완료된 매칭만" in str(exc.value)


def test_cancel_returns_offer_to_the_feed(db, seeded, committee_mode):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.cancel(db, match, seeded["member1"], "후원자 사정")

    assert match.status is MatchStatus.CANCELLED
    assert offer.status is OfferStatus.OPEN
    assert case.status is CaseStatus.OPEN


def test_report_contains_no_identifying_data(client, db, seeded, member_mode):
    """월간 보고서는 비식별 코드만으로 만들어진다 — 그대로 시청에 제출 가능해야 한다."""
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.mark_delivered(db, match, seeded["member1"], "전달")

    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    html = client.get("/member/report").text

    assert case.code in html                      # 비식별 코드는 들어간다
    for secret in ("홍길동", "김철수", "이영희", "010-0000"):
        assert secret not in html
