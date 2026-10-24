"""위원이 생기는 두 길 — 초대 코드와 관리자 대리 등록.

둘 다 둔 이유는 위촉 현장이 두 가지이기 때문이다. 회의 자리에서 명단을 받아 관리자가
넣는 경우와, 위촉장을 받은 분이 각자 휴대폰으로 가입하는 경우.

코드 쪽에는 네 가지가 붙어 있다 — 유효기간, 사용 횟수 한도, 무효화, 승인 대기. 앞의 셋은
코드가 새는 범위를 줄이고 마지막 하나는 새어도 막는다. 위원은 도움이 필요한 가정의 실명과
연락처를 읽는 사람이라, 코드 하나가 단체 대화방에 잘못 올라가는 것이 곧 유출이 되면 안 된다.

이 파일은 그 네 가지가 실제로 막는지, 그리고 승인 전에는 어느 화면도 열리지 않는지를
고정한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import accounts, invites
from app.models import Council, MemberInvite, Role, User
from app.models.invite import CODE_ALPHABET, CODE_LENGTH

JOIN = "/c/sunbu3/join"


def _login(client, email: str, password: str = "ium1234") -> None:
    client.post("/login", data={"email": email, "password": password})


@pytest.fixture()
def manager(db, seeded) -> User:
    """선부3동 관리자 — conftest 의 member1 이 매니저다 (안건 14)."""
    return seeded["member1"]


@pytest.fixture()
def code(db, manager) -> MemberInvite:
    return invites.create(db, manager, days=14, max_uses=1, note="2026-12-10 위촉")


def _join(client, code: str, *, name="새 위원", email="new@ium.test", pw="ium-new-2026"):
    return client.post(
        JOIN,
        data={"code": code, "name": name, "email": email, "password": pw, "confirm": pw},
    )


# --- 코드 모양 ---------------------------------------------------------------


def test_the_code_avoids_letters_people_confuse(db):
    """전화로 불러 주는 값이다. 0/O, 1/I/l 이 섞이면 "영이에요 오예요" 를 묻게 된다."""
    for forbidden in "01OIL":
        assert forbidden not in CODE_ALPHABET
    assert CODE_LENGTH >= 8  # 추측으로 맞히기 어려울 만큼은 길어야 한다


def test_a_code_typed_loosely_still_works(client, db, code):
    """소문자로 적거나 하이픈을 넣어 보내는 일이 흔하다.

    모양만 다른 입력을 틀렸다고 돌려보내면, 본인은 맞게 적었다고 생각해 코드가
    잘못된 줄 안다.
    """
    sloppy = code.code.lower()[:4] + "-" + code.code.lower()[4:]
    _join(client, sloppy)
    assert db.scalar(select(User).where(User.email == "new@ium.test")) is not None


# --- 발급 권한 ---------------------------------------------------------------


def test_only_a_manager_issues_codes(db, seeded):
    """위원을 들이는 사람과 후원자를 승인하는 사람이 같다 (2026-10-24 결정)."""
    for key in ("member2", "office", "donor"):
        with pytest.raises(invites.InviteError, match="매니저"):
            invites.create(db, seeded[key])


def test_a_code_belongs_to_the_managers_council(db, manager, code):
    assert code.council_id == manager.council_id
    assert code.created_by_id == manager.id


def test_the_issue_form_refuses_nonsense_limits(db, manager):
    for days in ("0", "-3", "999", "곧"):
        with pytest.raises(invites.InviteError):
            invites.create(db, manager, days=days)
    for uses in ("0", "99", "많이"):
        with pytest.raises(invites.InviteError):
            invites.create(db, manager, max_uses=uses)


# --- 네 가지 방어 -------------------------------------------------------------


def test_an_expired_code_stops_working(client, db, manager, code):
    """유효기간. 위촉이 끝난 뒤에도 살아 있는 코드가 가장 오래 새어 있는 코드다."""
    code.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    body = _join(client, code.code).text
    assert "유효기간이 지났습니다" in body
    assert db.scalar(select(User).where(User.email == "new@ium.test")) is None


def test_a_code_runs_out_of_uses(client, db, manager, code):
    """사용 횟수. 한 사람에게 준 코드가 열 사람을 들이는 길이 되지 않게."""
    _join(client, code.code, email="first@ium.test")
    db.expire_all()
    assert db.get(MemberInvite, code.id).used_count == 1

    body = _join(client, code.code, email="second@ium.test").text
    assert "사용 횟수를 모두" in body
    assert db.scalar(select(User).where(User.email == "second@ium.test")) is None


def test_a_code_with_several_uses_lets_several_in(client, db, manager):
    """회의에서 세 명을 위촉했다면 한 코드로 세 명이 들어온다."""
    three = invites.create(db, manager, days=14, max_uses=3)
    for i in range(3):
        _join(client, three.code, email=f"m{i}@ium.test")
    db.expire_all()
    assert db.get(MemberInvite, three.id).used_count == 3
    assert db.get(MemberInvite, three.id).is_usable is False


def test_revoking_a_code_keeps_the_record(client, db, manager, code):
    """무효화는 지우지 않고 표시한다 — 누가 그 코드로 들어왔는지 설명해야 한다."""
    invites.revoke(db, manager, code)

    assert code.revoked_by_id == manager.id
    assert db.get(MemberInvite, code.id) is not None
    assert code.state_label == "무효화됨"

    body = _join(client, code.code).text
    assert "무효화된 초대 코드" in body
    assert db.scalar(select(User).where(User.email == "new@ium.test")) is None


def test_revoking_twice_is_refused(db, manager, code):
    invites.revoke(db, manager, code)
    with pytest.raises(invites.InviteError, match="이미 무효화"):
        invites.revoke(db, manager, code)


def test_a_wrong_code_locks_the_join_screen(client, db, seeded, manager):
    """코드를 무한히 넣어 볼 수 있으면 위원 자리가 추측으로 열린다.

    잠금은 시간이 지나 풀리지 않고 관리자가 푼다 — 계정 잠금과 같다 (안건 15).
    """
    council = seeded["council"]
    for i in range(invites.MAX_FAILED_CODES - 1):
        body = _join(client, "WRONGXYZ", email=f"x{i}@ium.test").text
        assert "올바르지 않습니다" in body

    db.expire_all()
    assert db.get(Council, council.id).join_is_locked is False

    body = _join(client, "WRONGXYZ", email="last@ium.test").text
    assert "잠겼습니다" in body
    db.expire_all()
    assert db.get(Council, council.id).join_is_locked is True

    # 잠긴 뒤에는 맞는 코드도 통하지 않는다
    code = invites.create(db, manager)
    body = _join(client, code.code).text
    assert "잠겼" in body
    assert db.scalar(select(User).where(User.email == "new@ium.test")) is None


def test_a_successful_join_clears_the_failure_count(client, db, seeded, code):
    """남의 오타가 쌓여 모집이 막히는 상황을 조금이라도 줄인다."""
    council = seeded["council"]
    _join(client, "WRONGXYZ", email="x@ium.test")
    db.expire_all()
    assert db.get(Council, council.id).join_failed_attempts == 1

    _join(client, code.code)
    db.expire_all()
    assert db.get(Council, council.id).join_failed_attempts == 0


def test_the_manager_unlocks_the_join_screen(client, db, seeded, manager):
    council = seeded["council"]
    for i in range(invites.MAX_FAILED_CODES):
        _join(client, "WRONGXYZ", email=f"x{i}@ium.test")
    db.expire_all()
    assert db.get(Council, council.id).join_is_locked is True

    _login(client, "member1@ium.test")
    assert "위원 가입이 잠겨 있습니다" in client.get("/member/manage").text
    client.post("/member/manage/join/unlock")

    db.expire_all()
    refreshed = db.get(Council, council.id)
    assert refreshed.join_is_locked is False
    assert refreshed.join_failed_attempts == 0


def test_only_a_manager_unlocks_the_join_screen(db, seeded):
    with pytest.raises(invites.InviteError, match="매니저"):
        invites.unlock_join(db, seeded["member2"], seeded["council"])


# --- 승인 대기 ---------------------------------------------------------------


def test_a_code_join_waits_for_approval(client, db, code):
    """코드만으로 계정이 서면 안 된다. 코드가 새어도 여기서 막힌다."""
    _join(client, code.code)
    member = db.scalar(select(User).where(User.email == "new@ium.test"))

    assert member.role is Role.MEMBER
    assert member.approved_at is None
    assert member.is_approved is False
    assert member.must_change_password is False  # 비밀번호를 본인이 정했다


def test_a_pending_member_opens_no_screen(client, db, code):
    """승인 전에는 어느 화면도 열리지 않는다. 위원 화면은 곧 식별정보 화면이다."""
    _join(client, code.code)
    client.post("/login", data={"email": "new@ium.test", "password": "ium-new-2026"})

    for path in ("/member", "/member/donors", "/member/matches", "/member/report"):
        body = client.get(path).text
        assert "선부3동 A가정" not in body
        assert "승인" in body


def test_a_pending_member_sees_a_waiting_screen_not_a_loop(client, db, code):
    """승인 대기 계정을 역할 홈으로 보내면 403 → 홈 → 역할 홈으로 돌았다.

    오류가 나는 자리로 되돌리는 안내는 그 자리가 막힌 화면일 때 무한히 돈다.
    """
    _join(client, code.code)
    res = client.post(
        "/login", data={"email": "new@ium.test", "password": "ium-new-2026"},
        follow_redirects=False,
    )
    assert res.status_code == 303

    page = client.get("/")   # 리다이렉트를 따라간다 — 돌면 여기서 터진다
    assert page.status_code == 200
    assert "관리자 승인을 기다리는 중입니다" in page.text


def test_a_pending_member_can_still_log_in_to_check(client, db, code):
    """본인이 "가입이 됐는지" 를 확인할 길은 있어야 한다. 로그인은 되고 화면이 알려 준다."""
    _join(client, code.code)
    res = client.post(
        "/login", data={"email": "new@ium.test", "password": "ium-new-2026"},
        follow_redirects=True,
    )
    assert "기다리는 중입니다" in res.text


def test_the_manager_approves_and_the_screens_open(client, db, seeded, code):
    _join(client, code.code)
    member = db.scalar(select(User).where(User.email == "new@ium.test"))

    _login(client, "member1@ium.test")
    page = client.get("/member/manage").text
    assert "승인 대기 위원" in page
    assert "새 위원" in page

    client.post(f"/member/manage/members/{member.id}/approve")
    db.expire_all()
    assert db.get(User, member.id).is_approved is True

    client.post("/login", data={"email": "new@ium.test", "password": "ium-new-2026"})
    assert "케이스" in client.get("/member").text


def test_rejecting_keeps_the_account_as_a_record(client, db, seeded, code):
    """코드가 새어 들어온 가입이라면 그 사실이 남아야 한다 — 지우면 답할 수 없다."""
    _join(client, code.code)
    member = db.scalar(select(User).where(User.email == "new@ium.test"))

    _login(client, "member1@ium.test")
    client.post(
        f"/member/manage/members/{member.id}/reject",
        data={"reason": "위촉 명단에 없는 분"},
    )

    db.expire_all()
    rejected = db.get(User, member.id)
    assert rejected is not None
    assert rejected.is_active is False
    assert rejected.approved_at is None

    from app.models import AccountEvent

    events = db.scalars(
        select(AccountEvent).where(AccountEvent.user_id == member.id)
    ).all()
    assert any(e.action == "reject_member" and "명단에 없는" in (e.note or "") for e in events)


def test_rejecting_needs_a_reason(db, seeded, code, client):
    _join(client, code.code)
    member = db.scalar(select(User).where(User.email == "new@ium.test"))
    with pytest.raises(accounts.AccountError, match="사유"):
        accounts.reject_member(db, seeded["member1"], member, "  ")


def test_only_a_manager_approves_a_member(db, seeded, code, client):
    _join(client, code.code)
    member = db.scalar(select(User).where(User.email == "new@ium.test"))
    with pytest.raises(accounts.AccountError, match="매니저"):
        accounts.approve_member(db, seeded["member2"], member)


def test_approving_twice_is_refused(db, seeded, code, client):
    _join(client, code.code)
    member = db.scalar(select(User).where(User.email == "new@ium.test"))
    accounts.approve_member(db, seeded["member1"], member)
    with pytest.raises(accounts.AccountError, match="이미 승인"):
        accounts.approve_member(db, seeded["member1"], member)


# --- 관리자 대리 등록 ---------------------------------------------------------


def test_a_member_issued_by_the_manager_needs_no_approval(client, db, seeded):
    """관리자가 이름과 이메일을 받아 직접 넣은 계정은 발급이 곧 승인이다."""
    _login(client, "member1@ium.test")
    res = client.post(
        "/member/manage/members",
        data={"name": "직접 등록 위원", "email": "direct@ium.test", "note": "회의 명단"},
    )
    assert "임시 비밀번호" in res.text
    assert res.headers.get("cache-control") == "no-store"

    member = db.scalar(select(User).where(User.email == "direct@ium.test"))
    assert member.is_approved is True
    assert member.approved_by_id == seeded["member1"].id
    assert member.must_change_password is True  # 본인이 화면 앞에 없으므로 임시 값이다


def test_the_temporary_password_never_reaches_the_cookie(client, db, seeded):
    import base64
    import re

    _login(client, "member1@ium.test")
    res = client.post(
        "/member/manage/members",
        data={"name": "직접 등록 위원", "email": "direct@ium.test", "note": ""},
    )
    temp = re.search(r'<input value="([^"]+)" readonly', res.text).group(1)
    cookie = client.cookies.get("session") or ""
    assert cookie, "세션 쿠키가 없으면 이 테스트는 아무것도 증명하지 않는다"
    assert temp not in cookie
    assert temp.encode() not in base64.urlsafe_b64decode(cookie.split(".")[0] + "==")


# --- 협의체 경계 -------------------------------------------------------------


def test_a_code_does_not_work_in_another_council(client, db, seeded, other_council, code):
    """선부3동 코드로 선부2동 위원이 될 수는 없다."""
    other_council.approved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()

    body = client.post(
        "/c/sunbu2/join",
        data={"code": code.code, "name": "엉뚱한 위원", "email": "wrong@ium.test",
              "password": "ium-new-2026", "confirm": "ium-new-2026"},
    ).text
    assert "올바르지 않습니다" in body or "잠겼" in body
    assert db.scalar(select(User).where(User.email == "wrong@ium.test")) is None


def test_a_manager_only_sees_their_own_codes(client, db, seeded, other_council, code):
    other_manager = User(
        email="mg@sunbu2.test",
        password_hash=accounts.hash_password("ium1234"),
        name="선부2동 관리자",
        role=Role.MEMBER,
        council_id=other_council.id,
        is_manager=True,
        approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(other_manager)
    db.commit()

    theirs = invites.create(db, other_manager, days=7, max_uses=1)

    assert [i.id for i in invites.listing(db, seeded["council"].id)] == [code.id]
    assert [i.id for i in invites.listing(db, other_council.id)] == [theirs.id]

    _login(client, "member1@ium.test")
    body = client.get("/member/manage").text
    assert code.code in body
    assert theirs.code not in body


def test_a_manager_cannot_revoke_another_councils_code(client, db, seeded, other_council):
    other_manager = User(
        email="mg@sunbu2.test",
        password_hash=accounts.hash_password("ium1234"),
        name="선부2동 관리자",
        role=Role.MEMBER,
        council_id=other_council.id,
        is_manager=True,
        approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(other_manager)
    db.commit()
    theirs = invites.create(db, other_manager, days=7, max_uses=1)

    _login(client, "member1@ium.test")
    body = client.post(f"/member/manage/invites/{theirs.id}/revoke").text

    assert "다른 협의체" in body
    db.expire_all()
    assert db.get(MemberInvite, theirs.id).is_revoked is False


def test_the_join_address_is_not_the_signup_address(client, db, seeded, code):
    """위원과 후원자의 가입 주소를 나눈 이유 — 잘못 고른 가입은 되돌리기 번거롭다."""
    join = client.get(JOIN).text
    signup = client.get("/c/sunbu3/signup").text

    assert "초대 코드" in join
    assert "초대 코드" not in signup
    assert "나눔가게로" in signup
    assert "나눔가게로" not in join


def test_the_two_approvals_block_different_things(client, db, seeded):
    """위원 승인과 후원자 승인은 같은 장치가 아니다.

    처음 승인 관문을 걸 때 역할을 가리지 않았고, 그래서 승인 전 후원자가 가게도 나눔글도
    올릴 수 없게 됐다. 그건 안건 10 의 결정과 반대다 — 올릴 수조차 없으면 승인을 기다릴
    이유가 사라진다.

      위원 승인  : 식별정보를 읽을 수 있는 사람을 늘린다 → 승인 전엔 화면이 안 열린다
      후원자 승인: 그 가게의 나눔이 위원의 매칭 후보에 오른다 → 승인 전에도 올릴 수 있다
    """
    waiting_donor = User(
        phone="01066660001",
        password_hash=accounts.hash_password("2026"),
        name="승인 대기 사장",
        role=Role.DONOR,
        council_id=seeded["council"].id,
    )
    db.add(waiting_donor)
    db.commit()
    assert waiting_donor.is_approved is False

    client.post("/login", data={"phone": "010-6666-0001", "pin": "2026"})
    assert client.get("/donor/post").status_code == 200
    client.post(
        "/donor/shop",
        data={"name": "대기분식", "category": "분식", "address": "", "walk_minutes": ""},
    )
    db.expire_all()
    assert db.get(User, waiting_donor.id).shop is not None, "승인 전에도 가게는 등록된다"


def test_the_join_confirmation_is_not_overwritten(client, db, code):
    """가입 직후 안내가 403 문구로 덮이지 않는다.

    가입하면 세션이 열리고 역할 홈으로 가는데, 그 화면이 승인 대기로 막혀 있어서
    "관리자 승인을 기다리는 계정입니다" 가 방금 띄운 "가입 신청이 접수되었습니다" 를
    덮어썼다. 처음 가입한 사람에게는 접수가 됐다는 말이 먼저 필요하다.
    """
    body = _join(client, code.code).text
    assert "가입 신청이 접수되었습니다" in body
    assert "기다리는 중입니다" in body
