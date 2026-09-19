"""위원 흐름 테스트 — 매칭 취소와 케이스 종결.

취소가 막혀 있으면 나눔글은 RESERVED 로 굳고 후원자도 내릴 수 없다. 종결이 없으면
식별정보를 파기할 시점 자체가 오지 않는다. 두 경로가 뚫려 있어야 나머지가 돈다.
"""
from __future__ import annotations

from sqlalchemy import select

from app import matching
from app.models import Case, CaseStatus, Match, MatchStatus, Offer, OfferStatus


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _open_case_and_offer(db):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    return case, offer


# --- 매칭 취소 -------------------------------------------------------------


def test_cancel_returns_the_offer_to_the_donor(db, seeded, client):
    case, offer = _open_case_and_offer(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    assert offer.status is OfferStatus.RESERVED

    _login(client, "member1@ium.test")
    client.post(f"/member/matches/{match.id}/cancel", data={"reason": "가정 사정으로 수령 어려움"})

    db.expire_all()
    assert db.get(Match, match.id).status is MatchStatus.CANCELLED
    assert db.get(Offer, offer.id).status is OfferStatus.OPEN
    assert db.get(Case, case.id).status is CaseStatus.OPEN


def test_cancelled_offer_can_then_be_closed_by_the_donor(db, seeded, client):
    """후원자 화면의 '위원에게 알려 취소해 주세요' 안내가 실제로 통하는 경로인지 확인한다."""
    case, offer = _open_case_and_offer(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    _login(client, "member1@ium.test")
    client.post(f"/member/matches/{match.id}/cancel", data={"reason": "일정 불발"})

    _login(client, "blue@ium.test")
    client.post(f"/donor/offers/{offer.id}/close")

    db.expire_all()
    assert db.get(Offer, offer.id).status is OfferStatus.CLOSED


def test_cancel_reason_is_kept_on_the_match(db, seeded, client):
    case, offer = _open_case_and_offer(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    _login(client, "member1@ium.test")
    client.post(f"/member/matches/{match.id}/cancel", data={"reason": "중복 지원 확인됨"})

    db.expire_all()
    assert "중복 지원 확인됨" in db.get(Match, match.id).note


def test_only_the_owning_member_can_cancel(db, seeded, client):
    case, offer = _open_case_and_offer(db)
    match = matching.propose(db, case, offer, seeded["member1"])

    _login(client, "member2@ium.test")
    res = client.post(
        f"/member/matches/{match.id}/cancel", data={"reason": "남의 케이스"}, follow_redirects=False
    )

    assert res.headers["location"] == "/"
    db.expire_all()
    assert db.get(Match, match.id).status is not MatchStatus.CANCELLED


def test_only_the_owning_member_can_mark_delivered(db, seeded, client):
    case, offer = _open_case_and_offer(db)
    match = matching.propose(db, case, offer, seeded["member1"])
    assert match.status is MatchStatus.APPROVED

    _login(client, "member2@ium.test")
    client.post(f"/member/matches/{match.id}/deliver", data={"note": "", "thanks": ""})

    db.expire_all()
    assert db.get(Match, match.id).status is MatchStatus.APPROVED


# --- 케이스 종결 -----------------------------------------------------------


def test_close_case_sets_closed(db, seeded, client):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))

    _login(client, "member1@ium.test")
    client.post(f"/member/cases/{case.id}/close")

    db.expire_all()
    assert db.get(Case, case.id).status is CaseStatus.CLOSED


def test_cannot_close_a_case_with_a_live_match(db, seeded, client):
    case, offer = _open_case_and_offer(db)
    matching.propose(db, case, offer, seeded["member1"])

    _login(client, "member1@ium.test")
    body = client.post(f"/member/cases/{case.id}/close", follow_redirects=True).text

    assert "진행 중인 매칭이 있습니다" in body
    db.expire_all()
    assert db.get(Case, case.id).status is not CaseStatus.CLOSED


def test_closing_reminds_to_purge_remaining_identity(db, seeded, client):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    assert case.has_identity

    _login(client, "member1@ium.test")
    body = client.post(f"/member/cases/{case.id}/close", follow_redirects=True).text

    assert "식별정보가 아직 남아 있습니다" in body


def test_closed_case_cannot_be_matched(db, seeded, client):
    case, offer = _open_case_and_offer(db)

    _login(client, "member1@ium.test")
    client.post(f"/member/cases/{case.id}/close")
    body = client.post(
        "/member/matches",
        data={"case_id": case.id, "offer_id": offer.id},
        follow_redirects=True,
    ).text

    assert "종결된 케이스입니다." in body


def test_reopen_case(db, seeded, client):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))

    _login(client, "member1@ium.test")
    client.post(f"/member/cases/{case.id}/close")
    client.post(f"/member/cases/{case.id}/reopen")

    db.expire_all()
    assert db.get(Case, case.id).status is CaseStatus.OPEN


def test_only_the_owning_member_can_close(db, seeded, client):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))

    _login(client, "member2@ium.test")
    res = client.post(f"/member/cases/{case.id}/close", follow_redirects=False)

    assert res.headers["location"] == "/"
    db.expire_all()
    assert db.get(Case, case.id).status is not CaseStatus.CLOSED
