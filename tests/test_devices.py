"""기기 기억 · 후원자 메모 · 주소와 지도 테스트.

위원회 결정(2026-10-17, 안건 13):
- 전화번호를 아이디로, 로그인 시 인증번호. "본인 기기는 한동안 인증 없이 사용하고
  30일 경과 시 재인증한다."
- 선택 정보: 가게 이름, 주소, 우편번호. 주소는 지도에 표시해 "담당 위원 외 다른 봉사위원도
  가게를 쉽게 찾아갈 수 있게" 한다.
- "후원자별 메모를 누적 추가할 수 있으며 각 메모엔 날짜, 시간, 작성자, 내용이 함께 기록된다."
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from sqlalchemy import select

from app import accounts, devices  # noqa: F401
from app.models import DonorNote, Role, Shop, TrustedDevice, User
from app.models.device import TRUST_DAYS

PHONE = "010-6666-0001"
DIGITS = "01066660001"


def _signup(client, **over):
    data = {
        "name": "김행복",
        "phone": PHONE,
        "shop_name": "행복미용실",
        "pin": "2846",
        "confirm": "2846",
        **over,
    }
    return client.post("/signup", data=data, follow_redirects=False)


def _login_staff(client, email: str):
    return client.post(
        "/login", data={"email": email, "password": "ium1234"}, follow_redirects=False
    )


def _donor(db) -> User:
    return db.scalar(select(User).where(User.phone == DIGITS))


# --- 기기 기억 ---------------------------------------------------------------


def test_signing_up_remembers_the_device(db, client):
    _signup(client)

    assert client.cookies.get(devices.COOKIE_NAME)
    device = db.scalar(select(TrustedDevice))
    assert device is not None and device.user_id == _donor(db).id


def test_a_remembered_device_skips_the_pin(db, client):
    """가게를 보다 잠깐 들어오는 분에게 매번 숫자를 묻지 않는다."""
    _signup(client)
    client.cookies.delete("session")  # 세션은 끊고 기기 쿠키만 남긴다

    res = client.get("/login", follow_redirects=False)
    assert res.headers["location"] == "/donor"
    assert client.get("/donor/mine").status_code == 200


def test_the_token_is_not_stored_in_plain_text(db, client):
    """DB 가 유출돼도 그 값으로 로그인할 수 없어야 한다."""
    _signup(client)
    token = client.cookies.get(devices.COOKIE_NAME)
    device = db.scalar(select(TrustedDevice))

    assert device.token_hash != token
    assert len(device.token_hash) == 64  # sha256 hex


def test_the_memory_lasts_thirty_days(db, client):
    _signup(client)
    device = db.scalar(select(TrustedDevice))

    expires = device.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    days = (expires - datetime.now(timezone.utc)).days
    assert TRUST_DAYS - 1 <= days <= TRUST_DAYS


def test_an_expired_device_asks_for_the_pin_again(db, client):
    """"30일 경과 시 재인증" — 만료되면 다시 묻는다."""
    _signup(client)
    device = db.scalar(select(TrustedDevice))
    device.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    client.cookies.delete("session")

    res = client.get("/login", follow_redirects=False)
    assert res.status_code == 200  # 로그인 화면이 그대로 뜬다
    assert "후원자 로그인" in res.text


def test_an_expired_device_is_cleaned_up(db, client):
    """남겨 두면 '30일이면 재인증' 이 기록상으로만 참이 된다."""
    _signup(client)
    device = db.scalar(select(TrustedDevice))
    device.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    client.cookies.delete("session")

    client.get("/login")
    assert db.scalar(select(TrustedDevice)) is None


def test_logging_out_forgets_this_device(db, client):
    """끊지 않으면 로그아웃해도 로그인 화면에서 그대로 다시 들어간다."""
    _signup(client)
    client.get("/logout")

    assert db.scalar(select(TrustedDevice)) is None
    res = client.get("/login", follow_redirects=False)
    assert res.status_code == 200


def test_resetting_the_pin_cuts_every_device(db, seeded, client):
    """초기화는 보통 '못 들어간다'는 연락을 받고 한다. 잃어버린 휴대폰이 남으면 안 된다."""
    _signup(client)
    donor_id = _donor(db).id
    assert db.scalar(select(TrustedDevice)) is not None

    _login_staff(client, "member1@ium.test")
    client.post(f"/manage/donors/{donor_id}/reset")

    assert db.scalar(select(TrustedDevice).where(TrustedDevice.user_id == donor_id)) is None


def test_a_locked_account_cannot_slip_in_by_device(db, client):
    _signup(client)
    donor = _donor(db)
    donor.locked_at = datetime.now(timezone.utc)
    db.commit()
    client.cookies.delete("session")

    res = client.get("/login", follow_redirects=False)
    assert res.status_code == 200  # 통과하지 않는다


def test_a_forced_password_change_is_not_bypassed(db, seeded, client):
    """받은 숫자로 들어온 사람은 바꾸기 전에 기기로 우회할 수 없어야 한다."""
    _login_staff(client, "member1@ium.test")
    import re

    body = client.post(
        "/member/donors", data={"name": "박신입", "phone": "010-8888-0001"}
    ).text
    pin = re.search(r'class="temp-password"[^>]*>([0-9]+)<', body).group(1)
    client.get("/logout")

    client.post("/login", data={"phone": "010-8888-0001", "pin": pin})
    # 변경 전에는 기기를 기억하지 않는다
    assert db.scalar(
        select(TrustedDevice).join(User).where(User.phone == "01088880001")
    ) is None


def test_staff_devices_are_not_remembered(db, seeded, client):
    """위원·운영자는 식별정보와 승인 권한이 걸려 있어 기억해 두지 않는다."""
    _login_staff(client, "member1@ium.test")
    assert client.cookies.get(devices.COOKIE_NAME) is None
    assert db.scalar(select(TrustedDevice)) is None


def test_forget_all_counts_what_it_cut(db, seeded):
    donor = seeded["donor"]
    devices.remember(db, donor, "기기 A")
    devices.remember(db, donor, "기기 B")

    assert devices.forget_all(db, donor) == 2
    assert devices.forget_all(db, donor) == 0


def test_an_unknown_token_resolves_to_nobody(db):
    assert devices.resolve(db, None) is None
    assert devices.resolve(db, "아무거나") is None


# --- 주소와 지도 -------------------------------------------------------------


def test_signup_keeps_the_address_and_postal_code(db, client):
    _signup(client, address="안산시 단원구 선부동 123-4", postal_code="15236")

    shop = db.scalar(select(Shop).where(Shop.owner_id == _donor(db).id))
    assert shop.address == "안산시 단원구 선부동 123-4"
    assert shop.postal_code == "15236"


def test_postal_code_keeps_only_digits(db, client):
    _signup(client, postal_code="152-36")
    shop = db.scalar(select(Shop).where(Shop.owner_id == _donor(db).id))
    assert shop.postal_code == "15236"


def test_address_alone_still_creates_the_shop(db, client):
    """가게 이름이 없어도 주소만으로 찾아갈 수 있어야 한다."""
    _signup(client, shop_name="", address="안산시 단원구 선부동 1")
    shop = db.scalar(select(Shop).where(Shop.owner_id == _donor(db).id))
    assert shop is not None and shop.address == "안산시 단원구 선부동 1"


def test_the_map_link_searches_the_address(db, seeded):
    shop = db.scalar(select(Shop))
    shop.address = "안산시 단원구 선부동 123-4"
    db.commit()

    assert quote(shop.address) in shop.map_url
    assert shop.map_url.startswith("https://")


def test_no_address_means_no_map_link(db, seeded):
    shop = db.scalar(select(Shop))
    shop.address = None
    db.commit()
    assert shop.map_url is None


def test_any_member_sees_the_map_link_not_just_the_owner(db, seeded, client):
    """"담당 위원 외 다른 봉사위원도 가게를 쉽게 찾아갈 수 있게" 한다."""
    donor = seeded["donor"]
    donor.shop.address = "안산시 단원구 선부동 123-4"
    db.commit()

    for email in ("member1@ium.test", "member2@ium.test"):
        _login_staff(client, email)
        body = client.get(f"/member/donors/{donor.id}").text
        assert "지도에서 보기" in body, email
        assert "안산시 단원구 선부동 123-4" in body


def test_a_shop_without_an_address_says_so(db, seeded, client):
    donor = seeded["donor"]
    donor.shop.address = None
    db.commit()

    _login_staff(client, "member1@ium.test")
    body = client.get(f"/member/donors/{donor.id}").text
    assert "주소가 등록되지 않아" in body


# --- 후원자 메모 -------------------------------------------------------------


def test_a_member_adds_a_note_with_time_and_author(db, seeded, client):
    donor = seeded["donor"]
    _login_staff(client, "member2@ium.test")

    body = client.post(
        f"/member/donors/{donor.id}/notes",
        data={"body": "10/24 방문. 화요일 오전 반찬 5인분 가능."},
        follow_redirects=True,
    ).text

    assert "메모를 남겼습니다" in body
    note = db.scalar(select(DonorNote).where(DonorNote.donor_id == donor.id))
    assert note.author_id == seeded["member2"].id
    assert note.created_at is not None
    assert note.body == "10/24 방문. 화요일 오전 반찬 5인분 가능."


def test_notes_accumulate_newest_first(db, seeded, client):
    donor = seeded["donor"]
    _login_staff(client, "member1@ium.test")

    for text in ("첫 번째 메모", "두 번째 메모", "세 번째 메모"):
        client.post(f"/member/donors/{donor.id}/notes", data={"body": text})

    body = client.get(f"/member/donors/{donor.id}").text
    assert "메모 · 3개" in body
    assert body.index("세 번째 메모") < body.index("첫 번째 메모")


def test_notes_show_who_wrote_each_one(db, seeded, client):
    """"각 메모엔 날짜, 시간, 작성자, 내용이 함께 기록된다"."""
    donor = seeded["donor"]

    _login_staff(client, "member1@ium.test")
    client.post(f"/member/donors/{donor.id}/notes", data={"body": "이관희가 적은 메모"})
    _login_staff(client, "member2@ium.test")
    client.post(f"/member/donors/{donor.id}/notes", data={"body": "정미영이 적은 메모"})

    body = client.get(f"/member/donors/{donor.id}").text
    assert "이관희 위원" in body and "정미영 위원" in body


def test_an_empty_note_is_refused(db, seeded, client):
    donor = seeded["donor"]
    _login_staff(client, "member1@ium.test")

    body = client.post(
        f"/member/donors/{donor.id}/notes", data={"body": "   "}, follow_redirects=True
    ).text

    assert "메모 내용을 입력해 주세요" in body
    assert db.scalar(select(DonorNote)) is None


def test_notes_cannot_be_edited_or_deleted(db, seeded, client):
    """쌓이는 기록이다. '지난번에 뭐라고 했더라' 를 알려면 그때 적은 말이 남아야 한다."""
    donor = seeded["donor"]
    _login_staff(client, "member1@ium.test")
    client.post(f"/member/donors/{donor.id}/notes", data={"body": "원래 메모"})
    note = db.scalar(select(DonorNote))

    for path in (
        f"/member/donors/{donor.id}/notes/{note.id}/edit",
        f"/member/donors/{donor.id}/notes/{note.id}/delete",
    ):
        res = client.post(path, data={"body": "고친 메모"}, follow_redirects=False)
        assert res.status_code in (404, 405), path

    db.expire_all()
    assert db.get(DonorNote, note.id).body == "원래 메모"


def test_notes_are_refused_for_non_donors(db, seeded, client):
    _login_staff(client, "member1@ium.test")
    body = client.post(
        f"/member/donors/{seeded['member2'].id}/notes",
        data={"body": "위원에게 메모"},
        follow_redirects=True,
    ).text
    assert "후원자를 찾을 수 없습니다" in body


def test_donors_cannot_read_the_notes_about_them(db, seeded, client):
    """가게 메모는 위원들이 보는 기록이다."""
    donor = seeded["donor"]
    _login_staff(client, "member1@ium.test")
    client.post(f"/member/donors/{donor.id}/notes", data={"body": "내부 메모"})

    client.post("/login", data={"email": "blue@ium.test", "password": "ium1234"})
    res = client.get(f"/member/donors/{donor.id}", follow_redirects=False)
    assert res.headers["location"] == "/"


def test_the_donor_detail_screen_is_for_members(db, seeded, client):
    """후원자 상세는 위원의 자리다.

    "주소는 지도에 표시해 담당 위원 외 다른 봉사위원도 가게를 쉽게 찾아갈 수 있게 한다"
    (안건 13). 그래서 위원 누구나 보고, 후원자 본인은 보지 않는다 — 남의 가게 주소와
    위원들이 적어 둔 메모가 들어 있다.
    """
    client.post("/login", data={"email": "blue@ium.test", "password": "ium1234"})
    res = client.get(f"/member/donors/{seeded['donor'].id}", follow_redirects=False)
    assert res.headers["location"] == "/"

    for email in ("member1@ium.test", "member2@ium.test", "member3@ium.test"):
        _login_staff(client, email)
        assert client.get(f"/member/donors/{seeded['donor'].id}").status_code == 200


def test_the_detail_screen_lists_the_shops_offers(db, seeded, client):
    _login_staff(client, "member1@ium.test")
    body = client.get(f"/member/donors/{seeded['donor'].id}").text
    assert "이 가게의 나눔글" in body
    assert "이불 빨래 무료 세탁" in body


def test_note_helper_refuses_a_non_donor(db, seeded):
    with pytest.raises(accounts.AccountError) as exc:
        accounts.add_donor_note(db, seeded["member1"], seeded["member1"], "메모")
    assert "후원자에게만" in str(exc.value)
