"""오류가 사용자에게 도달하는 방식 테스트.

이 앱은 JSON API 가 아니라 화면이다. "가게를 먼저 등록해주세요" 같은 안내가
500 페이지로 바뀌어 버리면 detail 문구를 공들여 쓴 의미가 없다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Credit, Offer, OfferStatus, Role, User
from app.security import hash_password


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def test_unknown_offer_kind_is_guided_not_500(db, seeded, client):
    before = len(list(db.scalars(select(Offer)).all()))
    _login(client, "blue@ium.test")

    body = client.post(
        "/donor/offers",
        data={"title": "쌀", "kind": "NOPE", "delivery": "member_pickup"},
        follow_redirects=True,
    ).text

    assert "나눔 종류 값이 올바르지 않습니다" in body
    assert len(list(db.scalars(select(Offer)).all())) == before


def test_unknown_delivery_method_is_guided_not_500(db, seeded, client):
    _login(client, "blue@ium.test")

    body = client.post(
        "/donor/offers",
        data={"title": "쌀", "kind": "goods", "delivery": "NOPE"},
        follow_redirects=True,
    ).text

    assert "전달 방법 값이 올바르지 않습니다" in body


def test_unknown_credit_kind_is_guided_not_500(db, seeded, client):
    _login(client, "blue@ium.test")

    body = client.post("/donor/credits", data={"kind": "NOPE"}, follow_redirects=True).text

    assert "증빙 종류 값이 올바르지 않습니다" in body
    assert list(db.scalars(select(Credit)).all()) == []


def test_missing_shop_message_reaches_the_donor(db, seeded, client):
    """가게 없이 나눔글을 올리려 할 때 — detail 문구가 그대로 화면에 떠야 한다."""
    donor = User(
        email="noshop@ium.test", password_hash=hash_password("ium1234"),
        name="가게없음", role=Role.DONOR,
    )
    db.add(donor)
    db.commit()

    _login(client, "noshop@ium.test")
    body = client.post(
        "/donor/offers",
        data={"title": "쌀", "kind": "goods", "delivery": "member_pickup"},
        follow_redirects=True,
    ).text

    assert "가게를 먼저 등록해주세요." in body


def test_not_found_is_guided_not_500(db, seeded, client):
    _login(client, "blue@ium.test")

    body = client.post("/donor/offers/99999/close", follow_redirects=True).text

    assert "나눔글을 찾을 수 없습니다." in body


def test_matching_conflict_message_reaches_the_member(db, seeded, client, committee_mode):
    """이미 매칭 중인 나눔을 또 제안할 때 — matching.py 의 400 이 안내로 도착해야 한다."""
    from app import matching
    from app.models import Case, CaseStatus

    cases = list(db.scalars(select(Case).where(Case.status == CaseStatus.OPEN)).all())
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    matching.propose(db, cases[0], offer, seeded["member1"])

    _login(client, "member1@ium.test")
    body = client.post(
        "/member/matches",
        data={"case_id": cases[1].id, "offer_id": offer.id},
        follow_redirects=True,
    ).text

    assert "이미 매칭 중이거나 종료된 나눔입니다." in body


def test_referer_to_another_site_is_not_followed(db, seeded, client):
    """Referer 를 그대로 믿으면 외부 사이트로 튕겨내는 통로가 된다."""
    _login(client, "blue@ium.test")

    res = client.post(
        "/donor/offers/99999/close",
        headers={"referer": "https://evil.example/phish"},
        follow_redirects=False,
    )

    assert res.headers["location"] == "/"


def test_referer_within_the_site_returns_to_that_screen(db, seeded, client):
    _login(client, "blue@ium.test")

    res = client.post(
        "/donor/offers/99999/close",
        headers={"referer": "http://testserver/donor/mine"},
        follow_redirects=False,
    )

    assert res.headers["location"] == "/donor/mine"


def test_wrong_role_still_goes_home(db, seeded, client):
    _login(client, "blue@ium.test")

    res = client.get(
        "/member", headers={"referer": "http://testserver/donor"}, follow_redirects=False
    )

    assert res.headers["location"] == "/"
