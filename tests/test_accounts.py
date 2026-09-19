"""계정 발급 테스트.

운영 모드에서는 seed.py 가 막혀 있으므로 계정이 생기는 길은 두 개뿐이다 — 서버 명령으로
만드는 첫 운영자, 그리고 운영자가 앱에서 발급하는 위원. 그 두 길과, 임시 비밀번호가
새지 않는지·강제 변경이 실제로 막는지를 여기서 고정한다.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app import accounts
from app.models import AccountEvent, Role, User
from app.security import (
    MIN_PASSWORD_LENGTH,
    generate_temp_password,
    hash_password,
    validate_new_password,
    verify_password,
)

ROOT = Path(__file__).resolve().parent.parent


def _login(client, email: str, password: str = "ium1234"):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def _session_cookie(client) -> str:
    raw = client.cookies.get("session")
    if not raw:
        return ""
    head = raw.split(".")[0]
    return base64.urlsafe_b64decode(head + "=" * (-head.__len__() % 4)).decode("utf-8", "replace")


# --- 임시 비밀번호 ---------------------------------------------------------


def test_temp_password_avoids_characters_people_misread():
    """운영자가 소리 내어 불러 주거나 손으로 적어 전한다. 0·o, 1·l·i 가 섞이면 그 자리에서 막힌다."""
    for _ in range(50):
        temp = generate_temp_password()
        assert len(temp) == 14 and temp.count("-") == 2
        assert not set(temp) & set("01oli")


def test_temp_passwords_are_not_predictable():
    assert len({generate_temp_password() for _ in range(200)}) == 200


def test_temp_password_passes_its_own_rule():
    """발급한 임시 비밀번호가 변경 화면의 규칙에 걸리면 안 된다."""
    assert validate_new_password(generate_temp_password(), email="a@b.kr") is None


@pytest.mark.parametrize(
    "password,expect",
    [
        ("short", "10자 이상"),
        ("member@ium.test", "이메일과 같은"),
        ("MEMBER", "10자 이상"),
        ("member", "10자 이상"),
    ],
)
def test_weak_passwords_are_refused(password, expect):
    problem = validate_new_password(password, email="member@ium.test")
    assert problem is not None and expect in problem


def test_local_part_of_the_email_is_refused_too():
    assert validate_new_password("member1234", email="member1234@ium.test") is not None


# --- 첫 운영자 (서버 명령) --------------------------------------------------


def test_create_office_makes_a_usable_account(db, client):
    user = accounts.create_office(
        db, name="협의체 사무국", email="Office@Example.KR", password="첫-운영자-비밀번호"
    )

    assert user.role is Role.OFFICE
    assert user.email == "office@example.kr"  # 로그인이 소문자로 찾으므로 저장도 소문자
    # 본인이 정한 비밀번호라 변경을 강제하지 않는다
    assert user.must_change_password is False

    res = _login(client, "office@example.kr", "첫-운영자-비밀번호")
    assert res.headers["location"] == "/office"


def test_create_office_is_recorded_without_an_actor(db):
    user = accounts.create_office(db, name="사무국", email="a@b.kr", password="충분히-긴-비밀번호")

    event = db.scalar(select(AccountEvent).where(AccountEvent.user_id == user.id))
    assert event.action == "create_office"
    assert event.actor_id is None  # 서버 명령에는 행위자가 없다


@pytest.mark.parametrize(
    "kwargs,expect",
    [
        ({"name": "  ", "email": "a@b.kr", "password": "충분히-긴-비밀번호"}, "이름"),
        ({"name": "사무국", "email": "not-an-email", "password": "충분히-긴-비밀번호"}, "이메일 형식"),
        ({"name": "사무국", "email": "a@b.kr", "password": "short"}, "10자 이상"),
    ],
)
def test_create_office_refuses_bad_input(db, kwargs, expect):
    with pytest.raises(accounts.AccountError) as exc:
        accounts.create_office(db, **kwargs)
    assert expect in str(exc.value)
    assert db.scalar(select(User).where(User.email == "a@b.kr")) is None


def test_duplicate_email_is_refused_case_insensitively(db, seeded):
    with pytest.raises(accounts.AccountError) as exc:
        accounts.create_office(db, name="중복", email="OFFICE@ium.test", password="충분히-긴-비밀번호")
    assert "이미 쓰고 있는" in str(exc.value)


def test_create_office_command_runs_in_production_mode(tmp_path):
    """seed.py 와 달리 이 명령은 운영에서 돌아야 한다. 운영 첫 계정을 만들 유일한 길이다."""
    db_path = tmp_path / "prod.db"
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(ROOT),
        "IUM_ENV": "production",
        "IUM_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "IUM_SECRET_KEY": "x" * 48,
        "IUM_IDENTITY_KEY": "aUxwUFJ6ekJmTEZDaUZ6VUNCSjBqaFEzTVpYWmxZNVE=",
    }
    run = lambda args, **kw: subprocess.run(  # noqa: E731
        [sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=180, **kw
    )

    assert run(["-m", "alembic", "upgrade", "head"]).returncode == 0

    # 비밀번호는 명령줄이 아니라 표준입력으로 — 셸 기록과 프로세스 목록에 남지 않게
    made = run(
        ["-m", "app.create_office", "--email", "office@example.kr", "--name", "사무국"],
        input="운영-첫-비밀번호-2026\n",
    )
    assert made.returncode == 0, made.stderr
    assert "office@example.kr" in made.stdout

    # 같은 이메일로 또 만들면 거부
    again = run(
        ["-m", "app.create_office", "--email", "office@example.kr", "--name", "사무국"],
        input="운영-첫-비밀번호-2026\n",
    )
    assert again.returncode != 0
    assert "이미 쓰고 있는" in again.stderr


# --- 위원 계정 발급 ---------------------------------------------------------


def test_office_issues_a_member_account(db, seeded, client):
    _login(client, "office@ium.test")
    body = client.post(
        "/office/members",
        data={"name": "박신입", "email": "New@ium.test", "note": "2026-09-19 위촉"},
    ).text

    member = db.scalar(select(User).where(User.email == "new@ium.test"))
    assert member is not None and member.role is Role.MEMBER
    assert member.must_change_password is True
    assert member.appointed_note == "2026-09-19 위촉"

    # 임시 비밀번호가 화면에 한 번 보이고, 그 값으로 실제 로그인이 된다
    assert "박신입" in body and "한 번만 보입니다" in body
    temp = _temp_from(body)
    assert verify_password(temp, member.password_hash)


def _temp_from(html: str) -> str:
    import re

    match = re.search(r'class="temp-password"[^>]*>([a-z0-9-]+)<', html)
    assert match, "임시 비밀번호가 화면에 없습니다"
    return match.group(1)


def test_temp_password_never_enters_the_session_cookie(db, seeded, client):
    """식별정보와 같은 이유다 — 세션은 쿠키에 담기고, 서명만 되어 있어 열어 보면 읽힌다."""
    _login(client, "office@ium.test")
    body = client.post("/office/members", data={"name": "박신입", "email": "new@ium.test"}).text
    temp = _temp_from(body)

    cookie = _session_cookie(client)
    assert '"uid"' in cookie  # 쿠키를 실제로 열어 보고 있다는 확인
    assert temp not in cookie


def test_issued_page_is_not_cached(db, seeded, client):
    _login(client, "office@ium.test")
    res = client.post("/office/members", data={"name": "박신입", "email": "new@ium.test"})
    assert "no-store" in res.headers.get("cache-control", "")


def test_issuing_is_recorded_with_the_office_as_actor(db, seeded, client):
    _login(client, "office@ium.test")
    client.post("/office/members", data={"name": "박신입", "email": "new@ium.test", "note": "위촉"})

    member = db.scalar(select(User).where(User.email == "new@ium.test"))
    event = db.scalar(select(AccountEvent).where(AccountEvent.user_id == member.id))
    assert event.action == "issue"
    assert event.actor_id == seeded["office"].id
    assert event.note == "위촉"


def test_bad_issue_input_is_guided_not_500(db, seeded, client):
    _login(client, "office@ium.test")
    before = len(list(db.scalars(select(User)).all()))

    body = client.post(
        "/office/members", data={"name": "박신입", "email": "member1@ium.test"}, follow_redirects=True
    ).text

    assert "이미 쓰고 있는" in body
    assert len(list(db.scalars(select(User)).all())) == before


def test_only_office_can_issue_accounts(db, seeded, client):
    for email in ("member1@ium.test", "blue@ium.test"):
        _login(client, email)
        res = client.post(
            "/office/members", data={"name": "몰래", "email": "sneak@ium.test"}, follow_redirects=False
        )
        assert res.headers["location"] == "/", email
    assert db.scalar(select(User).where(User.email == "sneak@ium.test")) is None


# --- 첫 로그인 비밀번호 변경 강제 -------------------------------------------


def _issue(client, db, email: str = "new@ium.test") -> tuple[User, str]:
    _login(client, "office@ium.test")
    body = client.post("/office/members", data={"name": "박신입", "email": email}).text
    client.get("/logout")
    return db.scalar(select(User).where(User.email == email)), _temp_from(body)


def test_temp_password_login_lands_on_the_password_screen(db, seeded, client):
    member, temp = _issue(client, db)

    res = _login(client, member.email, temp)
    assert res.headers["location"] == "/account/password"


def test_every_other_screen_is_blocked_until_the_password_changes(db, seeded, client):
    member, temp = _issue(client, db)
    _login(client, member.email, temp)

    for path in ("/member", "/member/matches", "/member/report", "/office"):
        res = client.get(path, follow_redirects=False)
        assert res.headers["location"] == "/account/password", path


def test_the_forced_screen_hides_the_tabs_that_go_nowhere(db, seeded, client):
    member, temp = _issue(client, db)
    _login(client, member.email, temp)

    body = client.get("/account/password").text
    assert "임시 비밀번호로 들어오셨습니다" in body
    assert 'href="/member"' not in body


def test_setting_a_new_password_opens_the_app(db, seeded, client):
    member, temp = _issue(client, db)
    _login(client, member.email, temp)

    res = client.post(
        "/account/password",
        data={
            "current_password": temp,
            "new_password": "우리동네-나눔-2026",
            "confirm_password": "우리동네-나눔-2026",
        },
        follow_redirects=False,
    )

    assert res.headers["location"] == "/member"
    db.expire_all()
    assert db.get(User, member.id).must_change_password is False
    assert client.get("/member").status_code == 200


def test_the_temp_password_stops_working_after_the_change(db, seeded, client):
    member, temp = _issue(client, db)
    _login(client, member.email, temp)
    client.post(
        "/account/password",
        data={
            "current_password": temp,
            "new_password": "우리동네-나눔-2026",
            "confirm_password": "우리동네-나눔-2026",
        },
    )
    client.get("/logout")

    assert _login(client, member.email, temp).headers["location"] == "/login"
    assert _login(client, member.email, "우리동네-나눔-2026").headers["location"] == "/member"


@pytest.mark.parametrize(
    "data,expect",
    [
        ({"current_password": "틀린비밀번호"}, "지금 비밀번호가 맞지 않습니다"),
        ({"confirm_password": "다른-비밀번호-2026"}, "서로 다릅니다"),
        ({"new_password": "짧다", "confirm_password": "짧다"}, f"{MIN_PASSWORD_LENGTH}자 이상"),
    ],
)
def test_bad_password_change_is_guided_and_keeps_the_lock(db, seeded, client, data, expect):
    member, temp = _issue(client, db)
    _login(client, member.email, temp)

    form = {
        "current_password": temp,
        "new_password": "우리동네-나눔-2026",
        "confirm_password": "우리동네-나눔-2026",
        **data,
    }
    body = client.post("/account/password", data=form, follow_redirects=True).text

    assert expect in body
    db.expire_all()
    assert db.get(User, member.id).must_change_password is True


def test_reusing_the_current_password_is_refused(db, seeded, client):
    member, temp = _issue(client, db)
    _login(client, member.email, temp)

    body = client.post(
        "/account/password",
        data={"current_password": temp, "new_password": temp, "confirm_password": temp},
        follow_redirects=True,
    ).text

    assert "지금과 다른" in body


def test_anyone_logged_in_can_change_their_own_password(db, seeded, client):
    """강제된 사람만이 아니라 평소에도 바꿀 수 있어야 한다."""
    _login(client, "member1@ium.test")
    assert "비밀번호 바꾸기" in client.get("/account/password").text

    res = client.post(
        "/account/password",
        data={
            "current_password": "ium1234",
            "new_password": "새로-정한-비밀번호",
            "confirm_password": "새로-정한-비밀번호",
        },
        follow_redirects=False,
    )
    assert res.headers["location"] == "/member"

    client.get("/logout")
    assert _login(client, "member1@ium.test", "새로-정한-비밀번호").headers["location"] == "/member"


def test_password_screen_needs_a_login(db, seeded, client):
    assert client.get("/account/password", follow_redirects=False).headers["location"] == "/login"


# --- 비밀번호 초기화 ---------------------------------------------------------


def test_office_resets_a_forgotten_password(db, seeded, client):
    member = seeded["member1"]
    _login(client, "office@ium.test")

    body = client.post(f"/office/members/{member.id}/reset").text
    temp = _temp_from(body)
    client.get("/logout")

    assert _login(client, member.email, "ium1234").headers["location"] == "/login"  # 예전 것은 막힌다
    assert _login(client, member.email, temp).headers["location"] == "/account/password"


def test_reset_is_recorded_so_it_cannot_happen_quietly(db, seeded, client):
    """운영자가 위원 계정에 들어갈 수 있는 유일한 길이다. 막을 수 없으니 기록을 남긴다."""
    member = seeded["member1"]
    _login(client, "office@ium.test")
    client.post(f"/office/members/{member.id}/reset")

    event = db.scalar(
        select(AccountEvent)
        .where(AccountEvent.user_id == member.id, AccountEvent.action == "reset")
    )
    assert event is not None and event.actor_id == seeded["office"].id

    assert "비밀번호 초기화" in client.get("/office/members").text


def test_reset_refuses_a_non_member(db, seeded, client):
    _login(client, "office@ium.test")
    for target in (seeded["donor"].id, 99999):
        body = client.post(f"/office/members/{target}/reset", follow_redirects=True).text
        assert "위원을 찾을 수 없습니다" in body

    db.expire_all()
    assert db.get(User, seeded["donor"].id).must_change_password is False


def test_deactivation_and_restore_are_recorded(db, seeded, client):
    member = seeded["member2"]  # 담당 케이스가 없어 바로 해제된다
    _login(client, "office@ium.test")

    client.post(f"/office/members/{member.id}/toggle")
    client.post(f"/office/members/{member.id}/toggle")

    actions = [
        e.action
        for e in db.scalars(
            select(AccountEvent)
            .where(AccountEvent.user_id == member.id)
            .order_by(AccountEvent.id)
        ).all()
    ]
    assert actions == ["deactivate", "reactivate"]


def test_account_log_shows_who_did_what(db, seeded, client):
    _login(client, "office@ium.test")
    client.post("/office/members", data={"name": "박신입", "email": "new@ium.test"})

    body = client.get("/office/members").text
    assert "계정 기록" in body
    assert "위원 계정 발급" in body
    assert "협의체 운영자" in body  # 행위자


def test_account_log_is_office_only(db, seeded, client):
    for email in ("member1@ium.test", "blue@ium.test"):
        _login(client, email)
        assert client.get("/office/members", follow_redirects=False).headers["location"] == "/"


def test_permission_matrix_shows_the_account_boundary(db, seeded, client):
    _login(client, "office@ium.test")
    html = client.get("/office").text
    assert "account" in html and "account_log" in html


# --- 위촉 해제와의 관계 ------------------------------------------------------


def test_a_deactivated_member_cannot_log_in_even_with_a_fresh_password(db, seeded, client):
    """비밀번호 초기화는 위촉 해제를 되돌리지 않는다."""
    member = seeded["member2"]
    _login(client, "office@ium.test")
    client.post(f"/office/members/{member.id}/toggle")
    temp = _temp_from(client.post(f"/office/members/{member.id}/reset").text)
    client.get("/logout")

    assert _login(client, member.email, temp).headers["location"] == "/login"


def test_seeded_accounts_are_not_forced_to_change(db, seeded, client):
    """기존 계정은 이미 본인이 정한 비밀번호를 쓰고 있다. 갑자기 요구할 이유가 없다."""
    for key in ("office", "member1", "donor"):
        assert seeded[key].must_change_password is False


def test_new_user_defaults_to_no_forced_change(db):
    user = User(
        email="plain@ium.test", password_hash=hash_password("ium1234"), name="평범", role=Role.DONOR
    )
    db.add(user)
    db.commit()
    assert user.must_change_password is False
