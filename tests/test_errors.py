"""오류가 사용자에게 도달하는 방식 테스트.

이 앱은 JSON API 가 아니라 화면이다. "가게를 먼저 등록해주세요" 같은 안내가
500 페이지로 바뀌어 버리면 detail 문구를 공들여 쓴 의미가 없다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Offer, OfferStatus, Role, User
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


# --- 숫자 입력 -------------------------------------------------------------


def test_non_numeric_walk_minutes_is_guided_not_dropped(db, seeded, client):
    """예전에는 '5분'이라고 쓰면 오류 없이 빈 값으로 저장됐다. 적은 값이 조용히 사라지면 안 된다."""
    from app.models import Shop, User
    from app.security import hash_password

    owner = User(
        email="newshop@ium.test", password_hash=hash_password("ium1234"),
        name="새가게", role=Role.DONOR,
    )
    db.add(owner)
    db.commit()

    _login(client, "newshop@ium.test")
    body = client.post(
        "/donor/shop", data={"name": "새가게", "walk_minutes": "5분"}, follow_redirects=True
    ).text

    assert "숫자만 입력해 주세요" in body
    assert db.scalar(select(Shop).where(Shop.owner_id == owner.id)) is None


def test_out_of_range_walk_minutes_is_refused(db, seeded, client):
    from app.models import Shop, User
    from app.security import hash_password

    owner = User(
        email="newshop2@ium.test", password_hash=hash_password("ium1234"),
        name="새가게", role=Role.DONOR,
    )
    db.add(owner)
    db.commit()

    _login(client, "newshop2@ium.test")
    body = client.post(
        "/donor/shop", data={"name": "새가게", "walk_minutes": "999"}, follow_redirects=True
    ).text

    assert "1에서 60 사이" in body
    assert db.scalar(select(Shop).where(Shop.owner_id == owner.id)) is None


def test_blank_walk_minutes_still_means_unknown(db, seeded, client):
    """빈 칸은 '모른다'는 뜻이다. 이건 그대로 통과해야 한다."""
    from app.models import Shop, User
    from app.security import hash_password

    owner = User(
        email="newshop3@ium.test", password_hash=hash_password("ium1234"),
        name="새가게", role=Role.DONOR,
    )
    db.add(owner)
    db.commit()

    _login(client, "newshop3@ium.test")
    client.post("/donor/shop", data={"name": "새가게", "walk_minutes": "  "})

    shop = db.scalar(select(Shop).where(Shop.owner_id == owner.id))
    assert shop is not None and shop.walk_minutes is None


def test_non_numeric_household_size_is_guided(db, seeded, client):
    from app.models import Case

    _login(client, "member1@ium.test")
    body = client.post(
        "/member/cases",
        data={"code": "선부3동 Z가정", "need_summary": "반찬", "household_size": "네 명"},
        follow_redirects=True,
    ).text

    assert "숫자만 입력해 주세요" in body
    assert db.scalar(select(Case).where(Case.code == "선부3동 Z가정")) is None


def test_valid_household_size_is_kept(db, seeded, client):
    from app.models import Case

    _login(client, "member1@ium.test")
    client.post(
        "/member/cases",
        data={"code": "선부3동 Y가정", "need_summary": "반찬", "household_size": "4"},
    )

    case = db.scalar(select(Case).where(Case.code == "선부3동 Y가정"))
    assert case is not None and case.household_size == 4


def test_form_limits_come_from_the_server(db, seeded, client):
    """화면의 min/max 와 서버 검사가 어긋나면 브라우저는 통과시키고 서버가 막는다."""
    from app.forms import HOUSEHOLD_SIZE, WALK_MINUTES

    # 가게 등록 폼은 아직 가게가 없는 후원자에게만 보인다
    owner = User(
        email="formcheck@ium.test", password_hash=hash_password("ium1234"),
        name="새가게", role=Role.DONOR,
    )
    db.add(owner)
    db.commit()

    _login(client, "formcheck@ium.test")
    post = client.get("/donor/post").text
    assert f'min="{WALK_MINUTES[0]}" max="{WALK_MINUTES[1]}"' in post

    _login(client, "member1@ium.test")
    cases = client.get("/member").text
    assert f'min="{HOUSEHOLD_SIZE[0]}" max="{HOUSEHOLD_SIZE[1]}"' in cases
