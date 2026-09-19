"""나눔글 노출 심사와 매칭 테스트.

위원회 결정(2026-09-19, 안건 05)으로 승인의 자리가 매칭에서 나눔글로 옮겨졌다.
후원자가 올린 나눔글은 운영팀이 노출을 승인해야 위원에게 보이고, 그 뒤 어느 가정에
보낼지는 담당 위원이 혼자 정한다. 두 단계가 각자 자리를 지키는지 여기서 고정한다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import matching
from app.models import Case, CaseStatus, MatchStatus, Offer, OfferStatus, Shop


def _fresh_pair(db):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    return case, offer


def _new_offer(db, seeded, **kwargs) -> Offer:
    """후원자가 막 올린 나눔글 — 기본값(승인 대기)을 그대로 쓴다."""
    shop = db.scalar(select(Shop))
    offer = Offer(shop_id=shop.id, title="새 나눔", kind=next(iter(db.scalars(select(Offer)))).kind, **kwargs)
    db.add(offer)
    db.commit()
    return offer


# --- 나눔글 노출 심사 (운영팀) ---------------------------------------------


def test_a_new_offer_waits_for_the_office(db, seeded):
    """후원자가 올린 나눔은 바로 위원에게 가지 않는다. 협의체 이름으로 나가는 물건이라서다."""
    offer = _new_offer(db, seeded)
    assert offer.status is OfferStatus.PENDING


def test_approval_puts_the_offer_in_front_of_members(db, seeded):
    offer = _new_offer(db, seeded)
    matching.approve_offer(db, offer, seeded["office"], "현장 확인함")

    assert offer.status is OfferStatus.OPEN
    assert offer.reviewed_by_id == seeded["office"].id
    assert offer.reviewed_at is not None
    assert offer.review_note == "현장 확인함"


def test_rejection_keeps_the_reason_for_the_donor(db, seeded):
    """사유 없이 사라지면 후원자는 앱이 고장 난 줄 알거나 선의가 거절당했다고만 받아들인다."""
    offer = _new_offer(db, seeded)
    matching.reject_offer(db, offer, seeded["office"], "유통기한이 지난 품목입니다")

    assert offer.status is OfferStatus.REJECTED
    assert offer.review_note == "유통기한이 지난 품목입니다"


def test_rejection_requires_a_reason(db, seeded):
    offer = _new_offer(db, seeded)
    for blank in ("", "   "):
        with pytest.raises(Exception) as exc:
            matching.reject_offer(db, offer, seeded["office"], blank)
        assert "거절 사유" in str(exc.value)
    assert offer.status is OfferStatus.PENDING


def test_only_pending_offers_can_be_reviewed(db, seeded):
    _, approved = _fresh_pair(db)
    for action in (matching.approve_offer, matching.reject_offer):
        with pytest.raises(Exception) as exc:
            action(db, approved, seeded["office"], "사유")
        assert "승인 대기 중인 나눔글이 아닙니다" in str(exc.value)


def test_members_cannot_match_an_unapproved_offer(db, seeded):
    """심사를 건너뛰고 매칭되는 길이 있으면 승인 단계가 있으나 마나다."""
    case, _ = _fresh_pair(db)
    pending = _new_offer(db, seeded)

    with pytest.raises(Exception) as exc:
        matching.propose(db, case, pending, seeded["member1"])
    assert "운영팀 승인을 기다리는" in str(exc.value)


def test_approval_can_be_switched_off(db, seeded, no_offer_approval):
    """'향후에 번거로우면 승인 단계를 뺄 수도 있지 않을까' — 설정으로 열어 두었다."""
    assert matching.initial_offer_status() is OfferStatus.OPEN


# --- 매칭 (위원) -----------------------------------------------------------


def test_matching_needs_no_second_approval(db, seeded):
    """어느 가정에 보낼지는 그 가정을 아는 담당 위원의 판단으로 남는다."""
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    assert match.status is MatchStatus.APPROVED
    assert offer.status is OfferStatus.RESERVED
    assert case.status is CaseStatus.MATCHING


def test_offer_is_reserved_then_closed(db, seeded):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    matching.mark_delivered(db, match, seeded["member1"], "전달 완료")
    assert offer.status is OfferStatus.CLOSED
    assert case.status is CaseStatus.RESOLVED


def test_cannot_double_book_an_offer(db, seeded):
    case, offer = _fresh_pair(db)
    matching.propose(db, case, offer, seeded["member1"])

    other_case = db.scalar(select(Case).where(Case.id != case.id, Case.status == CaseStatus.OPEN))
    with pytest.raises(Exception) as exc:
        matching.propose(db, other_case, offer, seeded["member1"])
    assert "매칭 중이거나 종료" in str(exc.value)


def test_cannot_deliver_a_cancelled_match(db, seeded):
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.cancel(db, match, seeded["member1"], "후원자 사정")

    with pytest.raises(Exception) as exc:
        matching.mark_delivered(db, match, seeded["member1"])
    assert "진행 중인 매칭만" in str(exc.value)


def test_cancel_returns_offer_to_the_members(db, seeded):
    """취소해도 노출 승인은 다시 받지 않는다. 걸러야 할 것은 물건이지 무산된 사정이 아니다."""
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.cancel(db, match, seeded["member1"], "후원자 사정")

    assert match.status is MatchStatus.CANCELLED
    assert offer.status is OfferStatus.OPEN
    assert case.status is CaseStatus.OPEN


def test_report_contains_no_identifying_data(client, db, seeded):
    """월간 보고서는 비식별 코드만으로 만들어진다 — 그대로 시청에 제출 가능해야 한다."""
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.mark_delivered(db, match, seeded["member1"], "전달")

    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    html = client.get("/member/report").text

    assert case.code in html                      # 비식별 코드는 들어간다
    for secret in ("홍길동", "김철수", "이영희", "010-0000"):
        assert secret not in html
