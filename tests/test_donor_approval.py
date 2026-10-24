"""후원자 승인 화면 테스트.

위원회 결정(2026-10-17, 안건 10·16): 나눔글을 건건이 검증해 공개 여부를 정하는 방식은
폐기한다. 대신 후원자 자체를 검증한다. 봉사위원이 후원자를 발굴해 아이디를 만들고,
승인은 매니저가 처리한다.

안건 05 를 뒤집은 결정이라, 예전 경로(나눔글 노출 승인)가 남아 있지 않은지도 함께 본다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Case, Offer, OfferStatus, Role, Shop, User


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _register(client, phone="010-7777-0001", name="새사장", shop="새가게"):
    return client.post(
        "/member/donors", data={"name": name, "phone": phone, "shop_name": shop}
    )


def _waiting_donor(db) -> User:
    return db.scalar(select(User).where(User.role == Role.DONOR, User.approved_at.is_(None)))


# --- 폐기된 경로가 남아 있지 않은지 -----------------------------------------


def test_the_old_offer_review_routes_are_gone(db, seeded, client):
    """안건 05 의 나눔글 심사는 폐기됐다. 길이 남아 있으면 둘 중 어느 쪽이 사실인지 흐려진다."""
    offer_id = db.scalar(select(Offer.id))
    _login(client, "office@ium.test")

    for path in (f"/office/offers/{offer_id}/approve", f"/office/offers/{offer_id}/reject"):
        res = client.post(path, data={"note": "사유"}, follow_redirects=False)
        assert res.status_code in (404, 405), path


def test_offer_status_no_longer_has_a_review_state(db):
    assert {s.value for s in OfferStatus} == {"open", "reserved", "closed"}


def test_a_new_offer_is_open_right_away(db, seeded, client):
    """승인된 후원자의 나눔글은 바로 매칭 후보에 오른다."""
    _login(client, "blue@ium.test")
    client.post(
        "/donor/offers",
        data={"title": "라면 20박스", "kind": "goods", "delivery": "member_pickup"},
    )

    offer = db.scalar(select(Offer).where(Offer.title == "라면 20박스"))
    assert offer.status is OfferStatus.OPEN


# --- 위원이 발굴하고 매니저가 승인한다 ---------------------------------------


def test_any_member_can_register_a_donor(db, seeded, client):
    """가게를 찾아다니는 사람이 위원이다. 등록은 위원 누구나 할 수 있어야 한다."""
    _login(client, "member2@ium.test")  # 매니저가 아닌 위원
    _register(client)

    donor = db.scalar(select(User).where(User.phone == "01077770001"))
    assert donor is not None and donor.approved_at is None


def test_only_the_manager_sees_the_approve_button(db, seeded, client):
    _login(client, "member2@ium.test")
    _register(client)

    body = client.get("/member/donors").text
    assert "승인 대기" in body
    assert "매니저가 승인합니다" in body

    _login(client, "member1@ium.test")  # 매니저
    assert "/approve" in client.get("/member/donors").text


def test_manager_approves_and_the_shop_enters_the_pool(db, seeded, client):
    _login(client, "member2@ium.test")
    _register(client)
    donor = _waiting_donor(db)

    shop = db.scalar(select(Shop).where(Shop.owner_id == donor.id))
    offer = Offer(
        council_id=shop.council_id, shop_id=shop.id, title="반찬 10인분",
        kind=db.scalar(select(Offer)).kind,
    )
    db.add(offer)
    db.commit()

    case_id = db.scalar(select(Case.id).where(Case.member_id == seeded["member1"].id))
    _login(client, "member1@ium.test")
    assert "반찬 10인분" not in client.get(f"/member/cases/{case_id}").text

    body = client.post(f"/member/donors/{donor.id}/approve", follow_redirects=True).text
    assert "승인했습니다" in body

    db.expire_all()
    assert db.get(User, donor.id).approved_at is not None
    assert "반찬 10인분" in client.get(f"/member/cases/{case_id}").text


def test_a_plain_member_cannot_approve(db, seeded, client):
    _login(client, "member2@ium.test")
    _register(client)
    donor = _waiting_donor(db)

    res = client.post(f"/member/donors/{donor.id}/approve", follow_redirects=False)
    assert res.headers["location"] == "/"

    db.expire_all()
    assert db.get(User, donor.id).approved_at is None


def test_a_donor_cannot_approve_themselves(db, seeded, client):
    _login(client, "member2@ium.test")
    _register(client)
    donor = _waiting_donor(db)

    _login(client, "blue@ium.test")
    res = client.post(f"/member/donors/{donor.id}/approve", follow_redirects=False)
    assert res.headers["location"] == "/"


def test_approving_someone_who_is_not_a_donor_is_refused(db, seeded, client):
    _login(client, "member1@ium.test")
    body = client.post(
        f"/member/donors/{seeded['member2'].id}/approve", follow_redirects=True
    ).text
    assert "후원자를 찾을 수 없습니다" in body


# --- 승인 취소 ---------------------------------------------------------------


def test_unapproving_removes_the_shop_from_the_pool(db, seeded, client):
    donor = seeded["donor"]
    case_id = db.scalar(select(Case.id).where(Case.member_id == seeded["member1"].id))

    _login(client, "member1@ium.test")
    assert "이불 빨래 무료 세탁" in client.get(f"/member/cases/{case_id}").text

    client.post(
        f"/member/donors/{donor.id}/unapprove", data={"reason": "폐업"}, follow_redirects=True
    )

    db.expire_all()
    assert db.get(User, donor.id).approved_at is None
    assert "이불 빨래 무료 세탁" not in client.get(f"/member/cases/{case_id}").text


def test_unapproving_without_a_reason_is_refused(db, seeded, client):
    donor = seeded["donor"]
    _login(client, "member1@ium.test")

    body = client.post(
        f"/member/donors/{donor.id}/unapprove", data={"reason": "  "}, follow_redirects=True
    ).text
    assert "이유를 적어" in body

    db.expire_all()
    assert db.get(User, donor.id).approved_at is not None


# --- 후원자 쪽에서 보이는 것 --------------------------------------------------


def test_an_unapproved_donor_can_still_post_and_is_told_why(db, seeded, client):
    """승인 전에도 올려 둘 수 있다. 승인되는 순간 그동안 올린 것이 함께 보인다."""
    _login(client, "member1@ium.test")
    body = _register(client).text
    import re

    pin = re.search(r'class="temp-password"[^>]*>([0-9]+)<', body).group(1)
    client.get("/logout")

    client.post("/login", data={"phone": "010-7777-0001", "pin": pin})
    client.post(
        "/account/password",
        data={"current_password": pin, "new_password": "3571", "confirm_password": "3571"},
    )

    mine = client.get("/donor/mine").text
    assert "협의체 승인을 기다리고 있습니다" in mine

    # 안내는 등록 직후 응답에 실린다 (/donor 로 리다이렉트되며 소비된다)
    posted = client.post(
        "/donor/offers",
        data={"title": "미승인 나눔", "kind": "goods", "delivery": "member_pickup"},
        follow_redirects=True,
    ).text
    assert "협의체 승인이 끝나면" in posted
    assert "미승인 나눔" in client.get("/donor/mine").text


def test_an_unapproved_donors_offer_is_hidden_from_the_feed(db, seeded, client):
    """동네에 공개된 나눔은 승인된 가게의 것뿐이다."""
    _login(client, "member1@ium.test")
    _register(client)
    donor = _waiting_donor(db)
    shop = db.scalar(select(Shop).where(Shop.owner_id == donor.id))
    db.add(Offer(
        council_id=shop.council_id, shop_id=shop.id, title="숨은 나눔",
        kind=db.scalar(select(Offer)).kind,
    ))
    db.commit()

    _login(client, "blue@ium.test")
    assert "숨은 나눔" not in client.get("/donor").text


def test_members_see_the_approved_donor_list(db, seeded, client):
    _login(client, "member1@ium.test")
    body = client.get("/member/donors").text
    assert "승인된 후원자" in body
    assert "푸른세탁소" in body
