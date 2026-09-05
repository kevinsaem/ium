"""후원자 나눔글 관리 테스트.

'내가 올린 나눔이 지금 어떤 상태인가'와 '다 나갔으니 내린다'는 후원자가 앱을 다시
믿을지 말지를 가르는 지점이다. 특히 위원이 이미 어느 가정에 약속한 나눔(RESERVED)을
후원자가 조용히 내려버리지 못한다는 것을 여기서 고정한다.
"""
from __future__ import annotations

from sqlalchemy import select

from app import matching
from app.models import Case, CaseStatus, Offer, OfferStatus, Role, Shop, User
from app.security import hash_password


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _open_offer(db) -> Offer:
    return db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))


def test_mine_lists_own_offers(db, seeded, client):
    _login(client, "blue@ium.test")
    body = client.get("/donor/mine").text

    assert "내 나눔글" in body
    for title in ("이불 빨래 무료 세탁", "쌀 10kg", "도시락 5개", "도어록 수리"):
        assert title in body


def test_close_removes_offer_from_member_candidates(db, seeded, client):
    offer = _open_offer(db)
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))

    _login(client, "blue@ium.test")
    client.post(f"/donor/offers/{offer.id}/close", follow_redirects=False)
    db.expire_all()
    assert db.get(Offer, offer.id).status is OfferStatus.CLOSED

    # 위원의 매칭 후보 목록에서도 빠져야 한다 — 마감의 실질이 여기에 있다.
    _login(client, "member1@ium.test")
    assert offer.title not in client.get(f"/member/cases/{case.id}").text


def test_cannot_close_offer_a_member_is_matching(db, seeded, client, committee_mode):
    offer = _open_offer(db)
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    matching.propose(db, case, offer, seeded["member1"])
    assert offer.status is OfferStatus.RESERVED

    _login(client, "blue@ium.test")
    body = client.post(f"/donor/offers/{offer.id}/close", follow_redirects=True).text

    assert "위원이 매칭을 진행 중입니다" in body
    db.expire_all()
    assert db.get(Offer, offer.id).status is OfferStatus.RESERVED


def test_reopen_restores_a_closed_offer(db, seeded, client):
    offer = _open_offer(db)

    _login(client, "blue@ium.test")
    client.post(f"/donor/offers/{offer.id}/close", follow_redirects=False)
    client.post(f"/donor/offers/{offer.id}/reopen", follow_redirects=False)

    db.expire_all()
    assert db.get(Offer, offer.id).status is OfferStatus.OPEN


def test_delivered_offer_cannot_be_reopened(db, seeded, client, member_mode):
    offer = _open_offer(db)
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.mark_delivered(db, match, seeded["member1"])
    assert offer.status is OfferStatus.CLOSED

    _login(client, "blue@ium.test")
    body = client.post(f"/donor/offers/{offer.id}/reopen", follow_redirects=True).text

    assert "전달이 완료된 나눔글입니다" in body
    db.expire_all()
    assert db.get(Offer, offer.id).status is OfferStatus.CLOSED


def test_donor_cannot_close_another_donors_offer(db, seeded, client):
    offer = _open_offer(db)

    other = User(
        email="other@ium.test", password_hash=hash_password("ium1234"),
        name="옆집 사장", role=Role.DONOR,
    )
    db.add(other)
    db.flush()
    db.add(Shop(owner_id=other.id, name="옆집분식"))
    db.commit()

    _login(client, "other@ium.test")
    res = client.post(f"/donor/offers/{offer.id}/close", follow_redirects=False)

    # 403 은 main.py 의 핸들러가 안내 문구와 함께 홈으로 돌려보낸다.
    assert res.headers["location"] == "/"
    db.expire_all()
    assert db.get(Offer, offer.id).status is OfferStatus.OPEN
