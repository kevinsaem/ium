"""후원자 로그인 테스트.

위원회 결정(2026-09-19, 안건 07): 후원자는 스스로 아주 단순하게 가입하고, 휴대폰 번호와
숫자 4자리로 로그인한다. 운영자나 위원이 대신 등록해 줄 수도 있고, 초기화하면 전화번호
뒤 네 자리가 된다.

숫자 4자리는 1만 가지뿐이다. 그래서 이 파일은 '단순한가'만 보지 않고 '그 단순함을 어떻게
막아 두었는가'를 함께 고정한다.
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app import accounts
from app.models import AccountEvent, Role, Shop, User
from app.security import PIN_LENGTH, validate_pin, verify_password

PHONE = "010-5555-0001"
DIGITS = "01055550001"


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


def _pin_login(client, phone=PHONE, pin="2846"):
    return client.post("/login", data={"phone": phone, "pin": pin}, follow_redirects=False)


def _flash(client) -> str:
    return client.get("/login").text


def _pin_from(html: str) -> str:
    match = re.search(r'class="temp-password"[^>]*>([0-9]+)<', html)
    assert match, "숫자 4자리가 화면에 없습니다"
    return match.group(1)


# --- 숫자 4자리 규칙 ---------------------------------------------------------


def test_pin_must_be_four_digits():
    for bad in ("", "12", "12345", "abcd", "12a4"):
        assert validate_pin(bad) is not None
    assert validate_pin("2846") is None


def test_all_same_digits_are_refused():
    """가장 먼저 시도되는 값이다."""
    for bad in ("0000", "1111", "9999"):
        problem = validate_pin(bad)
        assert problem is not None and "같은 숫자" in problem


def test_phone_last_four_is_refused_when_choosing():
    """초기화하면 이 값이 된다. 그대로 다시 고르면 초기화한 것과 같다."""
    problem = validate_pin("0001", phone=DIGITS)
    assert problem is not None and "전화번호 뒤" in problem
    assert validate_pin("0001") is None  # 번호를 모르면 판단하지 않는다


def test_generated_pins_are_four_digits_and_varied():
    from app.security import generate_pin

    pins = {generate_pin() for _ in range(300)}
    assert all(len(p) == PIN_LENGTH and p.isdigit() for p in pins)
    assert len(pins) > 50  # 고정값이 아니다


# --- 전화번호 정규화 ---------------------------------------------------------


@pytest.mark.parametrize("written", ["010-5555-0001", "01055550001", " 010 5555 0001 "])
def test_phone_is_stored_the_same_however_it_is_typed(db, written):
    assert accounts.normalize_phone(written) == DIGITS


@pytest.mark.parametrize("bad", ["", "123", "9105555000", "010-5555-00011111", "abc"])
def test_malformed_phone_is_refused(db, bad):
    with pytest.raises(accounts.AccountError) as exc:
        accounts.normalize_phone(bad)
    assert "휴대폰 번호" in str(exc.value)


# --- 직접 가입 ---------------------------------------------------------------


def test_donor_signs_up_and_is_logged_in(db, client):
    res = _signup(client)
    assert res.headers["location"] == "/donor"

    donor = db.scalar(select(User).where(User.phone == DIGITS))
    assert donor is not None and donor.role is Role.DONOR
    assert donor.email is None  # 이메일은 받지 않는다
    assert donor.must_change_password is False  # 본인이 정한 숫자다
    assert verify_password("2846", donor.password_hash)


def test_signup_creates_the_shop_when_given(db, client):
    _signup(client)
    donor = db.scalar(select(User).where(User.phone == DIGITS))
    assert db.scalar(select(Shop).where(Shop.owner_id == donor.id)).name == "행복미용실"


def test_signup_without_a_shop_is_fine(db, client):
    _signup(client, shop_name="")
    donor = db.scalar(select(User).where(User.phone == DIGITS))
    assert db.scalar(select(Shop).where(Shop.owner_id == donor.id)) is None


def test_signup_is_recorded(db, client):
    _signup(client)
    donor = db.scalar(select(User).where(User.phone == DIGITS))
    event = db.scalar(select(AccountEvent).where(AccountEvent.user_id == donor.id))
    assert event.action == "signup"


@pytest.mark.parametrize(
    "over,expect",
    [
        ({"name": "  "}, "이름"),
        ({"phone": "123"}, "휴대폰 번호"),
        ({"pin": "1111", "confirm": "1111"}, "같은 숫자"),
        ({"confirm": "9999"}, "서로 다릅니다"),
        ({"pin": "12", "confirm": "12"}, "4자리"),
    ],
)
def test_bad_signup_is_guided_and_creates_nothing(db, client, over, expect):
    _signup(client, **over)
    assert expect in _flash(client)
    assert db.scalar(select(User).where(User.phone == DIGITS)) is None


def test_the_same_phone_cannot_sign_up_twice(db, client):
    _signup(client)
    client.get("/logout")
    _signup(client, name="다른사람", pin="3571", confirm="3571")

    assert "이미 등록된 휴대폰 번호" in _flash(client)
    assert len(list(db.scalars(select(User).where(User.phone == DIGITS)).all())) == 1


def test_signup_page_is_reachable_without_logging_in(db, client):
    body = client.get("/signup").text
    assert "후원자" in body and "휴대폰 번호" in body


# --- 로그인 -----------------------------------------------------------------


def test_donor_logs_in_with_phone_and_pin(db, client):
    _signup(client)
    client.get("/logout")

    assert _pin_login(client).headers["location"] == "/donor"
    assert client.get("/donor/mine").status_code == 200


def test_phone_can_be_typed_with_or_without_dashes(db, client):
    _signup(client)
    client.get("/logout")
    assert _pin_login(client, phone="01055550001").headers["location"] == "/donor"


def test_wrong_pin_does_not_reveal_whether_the_phone_exists(db, client):
    """'그런 번호 없습니다' 와 '숫자가 틀립니다' 를 구분해 주면 등록 여부를 알려 주는 셈이다."""
    _signup(client)
    client.get("/logout")

    _pin_login(client, pin="9876")
    known = _flash(client)
    _pin_login(client, phone="010-9999-9999", pin="9876")
    unknown = _flash(client)

    assert "올바르지 않습니다" in known and "올바르지 않습니다" in unknown


def test_staff_login_still_uses_email(db, seeded, client):
    res = client.post(
        "/login", data={"email": "member1@ium.test", "password": "ium1234"}, follow_redirects=False
    )
    assert res.headers["location"] == "/member"


def test_login_page_offers_both_doors(db, seeded, client):
    body = client.get("/login").text
    assert "후원자 로그인" in body and "위원 · 운영자 로그인" in body
    assert 'href="/signup"' in body


# --- 연속 실패 잠금 ----------------------------------------------------------


def test_repeated_wrong_pins_lock_the_account(db, client):
    _signup(client)
    client.get("/logout")
    donor = db.scalar(select(User).where(User.phone == DIGITS))

    for attempt in range(accounts.MAX_FAILED_LOGINS - 1):
        _pin_login(client, pin="9876")
        assert "남음" in _flash(client), attempt

    _pin_login(client, pin="9876")
    assert "잠겼습니다" in _flash(client)

    db.expire_all()
    assert accounts.lock_remaining(db.get(User, donor.id)) > 0

    # 맞는 숫자를 넣어도 잠금이 풀리기 전에는 들어갈 수 없다
    assert _pin_login(client).headers["location"] == "/login"


def test_a_success_clears_the_failure_count(db, client):
    _signup(client)
    client.get("/logout")
    donor_id = db.scalar(select(User.id).where(User.phone == DIGITS))

    _pin_login(client, pin="9876")
    _pin_login(client, pin="9876")
    db.expire_all()
    assert db.get(User, donor_id).failed_logins == 2

    _pin_login(client)
    db.expire_all()
    assert db.get(User, donor_id).failed_logins == 0


def test_locking_is_recorded(db, client):
    _signup(client)
    client.get("/logout")
    for _ in range(accounts.MAX_FAILED_LOGINS):
        _pin_login(client, pin="9876")

    event = db.scalar(select(AccountEvent).where(AccountEvent.action == "locked"))
    assert event is not None and "연속 실패" in event.note


def test_email_login_is_rate_limited_too(db, seeded, client):
    """막을 이유는 같다."""
    for _ in range(accounts.MAX_FAILED_LOGINS):
        client.post("/login", data={"email": "member1@ium.test", "password": "틀린비밀번호"})

    res = client.post(
        "/login", data={"email": "member1@ium.test", "password": "ium1234"}, follow_redirects=False
    )
    assert res.headers["location"] == "/login"  # 맞는 비밀번호도 막힌다


# --- 숫자 바꾸기 -------------------------------------------------------------


def test_donor_changes_their_own_pin(db, client):
    _signup(client)

    body = client.get("/account/password").text
    assert "숫자 4자리" in body

    res = client.post(
        "/account/password",
        data={"current_password": "2846", "new_password": "3571", "confirm_password": "3571"},
        follow_redirects=False,
    )
    assert res.headers["location"] == "/donor"

    client.get("/logout")
    assert _pin_login(client, pin="2846").headers["location"] == "/login"
    assert _pin_login(client, pin="3571").headers["location"] == "/donor"


@pytest.mark.parametrize(
    "data,expect",
    [
        ({"current_password": "0000"}, "지금 숫자 4자리가 맞지 않습니다"),
        ({"confirm_password": "9999"}, "서로 다릅니다"),
        ({"new_password": "1111", "confirm_password": "1111"}, "같은 숫자"),
        ({"new_password": "0001", "confirm_password": "0001"}, "전화번호 뒤"),
        ({"new_password": "2846", "confirm_password": "2846"}, "지금과 다른"),
    ],
)
def test_bad_pin_change_is_guided(db, client, data, expect):
    _signup(client)
    form = {
        "current_password": "2846",
        "new_password": "3571",
        "confirm_password": "3571",
        **data,
    }
    body = client.post("/account/password", data=form, follow_redirects=True).text
    assert expect in body


def test_pin_change_is_recorded(db, client):
    _signup(client)
    client.post(
        "/account/password",
        data={"current_password": "2846", "new_password": "3571", "confirm_password": "3571"},
    )
    donor = db.scalar(select(User).where(User.phone == DIGITS))
    assert db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == donor.id, AccountEvent.action == "change_pin"
        )
    ) is not None


# --- 대신 등록 ---------------------------------------------------------------


def _login_staff(client, email):
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


@pytest.mark.parametrize("who,path", [("office", "/office/donors"), ("member1", "/member/donors")])
def test_staff_registers_a_donor_on_their_behalf(db, seeded, client, who, path):
    """"연세가 있으시고 어려워할 수도 있으니까" — 운영자와 위원 모두 만들어 드릴 수 있다."""
    _login_staff(client, f"{who}@ium.test")
    body = client.post(
        path, data={"name": "박나눔", "phone": "010-7777-1234", "shop_name": "나눔상회"}
    ).text

    donor = db.scalar(select(User).where(User.phone == "01077771234"))
    assert donor is not None and donor.role is Role.DONOR
    assert donor.must_change_password is True  # 받은 숫자는 바꿔야 한다

    pin = _pin_from(body)
    assert verify_password(pin, donor.password_hash)


def test_registered_donor_must_change_the_pin_before_using_the_app(db, seeded, client):
    _login_staff(client, "office@ium.test")
    pin = _pin_from(
        client.post("/office/donors", data={"name": "박나눔", "phone": "010-7777-1234"}).text
    )
    client.get("/logout")

    assert _pin_login(client, phone="010-7777-1234", pin=pin).headers["location"] == "/account/password"
    assert client.get("/donor/mine", follow_redirects=False).headers["location"] == "/account/password"

    client.post(
        "/account/password",
        data={"current_password": pin, "new_password": "3571", "confirm_password": "3571"},
    )
    assert client.get("/donor/mine").status_code == 200


def test_the_given_pin_never_enters_the_session_cookie(db, seeded, client):
    import base64

    _login_staff(client, "office@ium.test")
    pin = _pin_from(
        client.post("/office/donors", data={"name": "박나눔", "phone": "010-7777-1234"}).text
    )

    raw = client.cookies.get("session")
    head = raw.split(".")[0]
    cookie = base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)).decode("utf-8", "replace")
    assert '"uid"' in cookie and pin not in cookie


def test_registration_is_recorded_with_the_staff_as_actor(db, seeded, client):
    _login_staff(client, "member1@ium.test")
    client.post("/member/donors", data={"name": "박나눔", "phone": "010-7777-1234"})

    donor = db.scalar(select(User).where(User.phone == "01077771234"))
    event = db.scalar(select(AccountEvent).where(AccountEvent.user_id == donor.id))
    assert event.action == "register"
    assert event.actor_id == seeded["member1"].id


def test_donors_cannot_register_other_donors(db, seeded, client):
    _signup(client)
    for path in ("/office/donors", "/member/donors"):
        res = client.post(
            path, data={"name": "몰래", "phone": "010-7777-1234"}, follow_redirects=False
        )
        assert res.headers["location"] == "/", path
    assert db.scalar(select(User).where(User.phone == "01077771234")) is None


# --- 초기화 -----------------------------------------------------------------


def test_reset_sets_the_pin_to_the_last_four_digits(db, seeded, client):
    _signup(client)
    client.get("/logout")
    donor_id = db.scalar(select(User.id).where(User.phone == DIGITS))

    _login_staff(client, "office@ium.test")
    body = client.post(f"/office/donors/{donor_id}/reset").text

    assert _pin_from(body) == DIGITS[-4:] == "0001"
    db.expire_all()
    assert db.get(User, donor_id).must_change_password is True


def test_reset_lets_a_locked_out_donor_back_in(db, seeded, client):
    _signup(client)
    client.get("/logout")
    for _ in range(accounts.MAX_FAILED_LOGINS):
        _pin_login(client, pin="9876")
    donor_id = db.scalar(select(User.id).where(User.phone == DIGITS))

    _login_staff(client, "office@ium.test")
    client.post(f"/office/donors/{donor_id}/reset")
    client.get("/logout")

    db.expire_all()
    assert accounts.lock_remaining(db.get(User, donor_id)) == 0
    assert _pin_login(client, pin="0001").headers["location"] == "/account/password"


def test_reset_is_recorded(db, seeded, client):
    _signup(client)
    client.get("/logout")
    donor_id = db.scalar(select(User.id).where(User.phone == DIGITS))

    _login_staff(client, "office@ium.test")
    client.post(f"/office/donors/{donor_id}/reset")

    event = db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == donor_id, AccountEvent.action == "reset"
        )
    )
    assert event.actor_id == seeded["office"].id
    assert "전화번호 뒤" in event.note


def test_reset_refuses_a_member(db, seeded, client):
    _login_staff(client, "office@ium.test")
    body = client.post(
        f"/office/donors/{seeded['member1'].id}/reset", follow_redirects=True
    ).text
    assert "후원자를 찾을 수 없습니다" in body
