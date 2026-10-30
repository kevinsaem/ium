"""계정 잠금과 운영팀 연락처 테스트.

위원회 결정(2026-10-17, 안건 15): 인증 5회 오류 시 계정 잠금. 잠김은 매니저 화면에
안내되고 매니저가 해제할 수 있다. 운영팀 연락처는 매니저가 설정 화면에서 직접 입력한다.

이 둘은 한 쌍이다 — 잠금이 시간이 지나 풀리지 않으므로, 연락처가 없으면 들어올 길이 없다.
"""
from __future__ import annotations

from sqlalchemy import select

from app import accounts, retention
from app.models import AccountEvent, User


def _login(client, email: str, password: str = "ium1234"):
    return client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )


def _lock_out(client, email: str) -> None:
    for _ in range(accounts.MAX_FAILED_LOGINS):
        _login(client, email, "틀린비밀번호")


# --- 잠금은 저절로 풀리지 않는다 ---------------------------------------------


def test_lock_does_not_expire_on_its_own(db, seeded, client):
    """10분 뒤 자동 해제로 두면 매니저 화면에 아무것도 뜨지 않는다."""
    _lock_out(client, "member2@ium.test")

    db.expire_all()
    locked = db.get(User, seeded["member2"].id)
    assert accounts.is_locked(locked)
    assert locked.locked_at is not None

    # 맞는 비밀번호로도 못 들어간다
    assert _login(client, "member2@ium.test").headers["location"] == "/login"


def test_locking_is_recorded(db, seeded, client):
    _lock_out(client, "member2@ium.test")
    event = db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == seeded["member2"].id, AccountEvent.action == "locked"
        )
    )
    assert event is not None and "연속 실패" in event.note


# --- 매니저가 해제한다 -------------------------------------------------------


def test_manager_sees_locked_accounts_and_unlocks(db, seeded, client):
    target = seeded["member2"]
    _lock_out(client, "member2@ium.test")

    _login(client, "member1@ium.test")  # 매니저
    body = client.get("/manage/people").text
    assert "잠긴 계정 · 1건" in body
    assert target.name in body

    body = client.post(f"/manage/unlock/{target.id}", follow_redirects=True).text
    assert "잠금을 해제했습니다" in body

    db.expire_all()
    assert not accounts.is_locked(db.get(User, target.id))

    client.get("/logout")
    assert _login(client, "member2@ium.test").headers["location"] == "/member"


def test_unlocking_is_recorded_with_the_manager(db, seeded, client):
    target = seeded["member2"]
    _lock_out(client, "member2@ium.test")

    _login(client, "member1@ium.test")
    client.post(f"/manage/unlock/{target.id}")

    event = db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == target.id, AccountEvent.action == "unlocked"
        )
    )
    assert event is not None and event.actor_id == seeded["member1"].id


def test_a_plain_member_cannot_unlock(db, seeded, client):
    """매니저가 아닌 위원에게 열어 두면 '매니저가 해제한다'는 결정이 무의미해진다."""
    target = seeded["donor"]
    target.locked_at = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    )
    db.commit()

    _login(client, "member2@ium.test")
    for path in ("/manage", f"/manage/unlock/{target.id}"):
        res = client.get(path, follow_redirects=False) if path.endswith("manage") else client.post(
            path, follow_redirects=False
        )
        assert res.headers["location"] == "/", path

    db.expire_all()
    assert accounts.is_locked(db.get(User, target.id))


def test_a_member_without_the_manager_flag_cannot_unlock(db, seeded, client):
    """잠금 해제는 관리자 몫이다 (안건 15).

    운영자 역할이 있던 자리다. 역할을 폐기하면서 '관리자가 아닌 위원' 이 그 자리를
    맡았다 — 위원이라는 것만으로는 잠금을 풀 수 없다는 것이 여전히 확인돼야 한다.
    """
    _lock_out(client, "member2@ium.test")

    _login(client, "member3@ium.test")
    res = client.get("/manage/people", follow_redirects=False)
    assert res.headers["location"] == "/"


def test_unlocking_an_open_account_is_refused(db, seeded, client):
    _login(client, "member1@ium.test")
    body = client.post(
        f"/manage/unlock/{seeded['donor'].id}", follow_redirects=True
    ).text
    assert "잠겨 있지 않습니다" in body


def test_resetting_a_pin_also_clears_the_lock(db, seeded, client):
    """잊어서 여러 번 틀린 경우가 대부분이다. 초기화하면 함께 풀어 준다."""
    donor = seeded["donor"]
    donor.phone = "01012340000"
    db.commit()
    donor_id = donor.id

    for _ in range(accounts.MAX_FAILED_LOGINS):
        client.post("/login", data={"phone": "010-1234-0000", "pin": "9999"})
    db.expire_all()
    assert accounts.is_locked(db.get(User, donor_id))

    _login(client, "member1@ium.test")
    client.post(f"/manage/donors/{donor_id}/reset")

    db.expire_all()
    assert not accounts.is_locked(db.get(User, donor_id))


# --- 운영팀 연락처 -----------------------------------------------------------


def test_manager_sets_the_team_contact(db, seeded, client):
    _login(client, "member1@ium.test")
    body = client.post(
        "/manage/contact",
        data={"contact": "선부3동 협의체 010-1234-5678"},
        follow_redirects=True,
    ).text

    assert "연락처를" in body
    db.expire_all()
    policy = retention.current(db)
    assert policy.team_contact == "선부3동 협의체 010-1234-5678"
    assert policy.updated_by_id == seeded["member1"].id


def test_the_contact_appears_on_the_login_screen(db, seeded, client):
    """잠긴 분이 어디로 연락할지 모르는 것이 잠금 자체보다 불편하다."""
    _login(client, "member1@ium.test")
    client.post("/manage/contact", data={"contact": "협의체 010-1234-5678"})
    client.get("/logout")

    assert "협의체 010-1234-5678" in client.get("/login").text


def test_the_lock_message_carries_the_contact(db, seeded, client):
    _login(client, "member1@ium.test")
    client.post("/manage/contact", data={"contact": "협의체 010-1234-5678"})
    client.get("/logout")

    _lock_out(client, "member2@ium.test")
    assert "협의체 010-1234-5678" in client.get("/login").text


def test_without_a_contact_the_message_still_points_to_the_team(db, seeded, client):
    _lock_out(client, "member2@ium.test")
    body = client.get("/login").text
    assert "운영팀에 연락" in body


def test_clearing_the_contact_is_allowed(db, seeded, client):
    _login(client, "member1@ium.test")
    client.post("/manage/contact", data={"contact": "협의체 010-1234-5678"})
    body = client.post(
        "/manage/contact", data={"contact": "  "}, follow_redirects=True
    ).text

    assert "비웠습니다" in body
    db.expire_all()
    assert retention.current(db).team_contact is None


def test_an_overlong_contact_is_refused(db, seeded, client):
    _login(client, "member1@ium.test")
    body = client.post(
        "/manage/contact", data={"contact": "가" * 200}, follow_redirects=True
    ).text
    assert "너무 깁니다" in body


def test_only_a_manager_sets_the_contact(db, seeded, client):
    for email in ("member2@ium.test", "member3@ium.test", "blue@ium.test"):
        _login(client, email)
        res = client.post(
            "/manage/contact", data={"contact": "몰래"}, follow_redirects=False
        )
        assert res.headers["location"] == "/", email

    db.expire_all()
    assert retention.current(db).team_contact is None


# --- 매니저 탭 ---------------------------------------------------------------


def test_the_manager_tab_shows_only_for_managers(db, seeded, client):
    _login(client, "member1@ium.test")
    assert 'href="/manage"' in client.get("/member").text

    _login(client, "member2@ium.test")
    assert 'href="/manage"' not in client.get("/member").text
