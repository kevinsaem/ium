"""후원자 승인과 매칭 테스트.

승인의 자리가 두 번 옮겨졌다 — 1차(안건 05)는 나눔글 노출 승인, 2차(안건 10)는 그 방식을
폐기하고 후원자 자체를 검증한다. 거르는 대상이 물건에서 사람으로 바뀌었다.

승인된 후원자의 나눔만 위원 후보에 오르는지, 그리고 그 경계를 우회할 길이 없는지 고정한다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import accounts, matching
from app.models import Case, CaseStatus, MatchStatus, Offer, OfferKind, OfferStatus, Shop


def _fresh_pair(db):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    return case, offer


# --- 후원자 승인 (매니저) -------------------------------------------------


def test_a_new_donor_waits_for_approval(db, seeded):
    """거르는 대상은 물건이 아니라 사람이다 (위원회 결정, 안건 10)."""
    donor, _ = accounts.register_donor(
        db, seeded["member1"], name="새사장", phone="010-7777-0001", shop_name="새가게"
    )
    assert donor.approved_at is None
    assert not donor.is_approved


def test_approval_puts_the_donors_offers_in_front_of_members(db, seeded):
    donor, _ = accounts.register_donor(
        db, seeded["member1"], name="새사장", phone="010-7777-0001", shop_name="새가게"
    )
    shop = db.scalar(select(Shop).where(Shop.owner_id == donor.id))
    offer = Offer(shop_id=shop.id, title="라면 20박스", kind=OfferKind.GOODS)
    db.add(offer)
    db.commit()

    assert offer.id not in [o.id for o in matching.open_offers_for_members(db)]

    accounts.approve_donor(db, seeded["member1"], donor)
    assert offer.id in [o.id for o in matching.open_offers_for_members(db)]


def test_members_cannot_match_an_unapproved_donors_offer(db, seeded):
    """후보 목록에서 빠지는 것만으로는 부족하다 — 주소를 직접 넣는 길이 있다."""
    donor, _ = accounts.register_donor(
        db, seeded["member1"], name="새사장", phone="010-7777-0001", shop_name="새가게"
    )
    shop = db.scalar(select(Shop).where(Shop.owner_id == donor.id))
    offer = Offer(shop_id=shop.id, title="라면 20박스", kind=OfferKind.GOODS)
    db.add(offer)
    db.commit()

    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    with pytest.raises(Exception) as exc:
        matching.propose(db, case, offer, seeded["member1"])
    assert "승인되지 않은 후원자" in str(exc.value)


def test_only_a_manager_approves(db, seeded):
    donor, _ = accounts.register_donor(
        db, seeded["member1"], name="새사장", phone="010-7777-0001"
    )
    with pytest.raises(accounts.AccountError) as exc:
        accounts.approve_donor(db, seeded["member2"], donor)  # 매니저 아님
    assert "매니저" in str(exc.value)
    assert donor.approved_at is None


def test_approval_records_who_approved(db, seeded):
    donor, _ = accounts.register_donor(
        db, seeded["member1"], name="새사장", phone="010-7777-0001"
    )
    accounts.approve_donor(db, seeded["member1"], donor)
    assert donor.approved_by_id == seeded["member1"].id


def test_approving_twice_is_refused(db, seeded):
    donor, _ = accounts.register_donor(
        db, seeded["member1"], name="새사장", phone="010-7777-0001"
    )
    accounts.approve_donor(db, seeded["member1"], donor)
    with pytest.raises(accounts.AccountError) as exc:
        accounts.approve_donor(db, seeded["member1"], donor)
    assert "이미 승인" in str(exc.value)


def test_unapproving_needs_a_reason_and_keeps_live_matches(db, seeded):
    """되돌리면 후보에서 빠지지만, 이미 약속된 매칭은 그대로 둔다."""
    case, offer = _fresh_pair(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    owner = offer.shop.owner

    with pytest.raises(accounts.AccountError):
        accounts.unapprove_donor(db, seeded["member1"], owner, "  ")

    accounts.unapprove_donor(db, seeded["member1"], owner, "폐업")
    assert owner.approved_at is None
    assert match.status is MatchStatus.APPROVED  # 진행 중인 매칭은 살아 있다


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
