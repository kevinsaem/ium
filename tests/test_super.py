"""계정이 생기는 길의 맨 위 — 슈퍼 관리자와 협의체 개설.

운영 모드에서는 seed.py 가 막혀 있어 계정은 위에서 아래로만 생긴다.

    python -m app.create_super  →  협의체 등록  →  관리자 발급  →  승인  →  전용 주소 가입

이 파일은 그 사슬이 끊기지 않는지, 그리고 중간을 건너뛸 수 없는지를 고정한다. 건너뛸 수
있으면 준비가 끝나기 전에 주소가 살아 있고, 그 주소로 들어온 주민의 전화번호가 아무도
보지 않는 화면에 쌓인다.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from app import accounts, councils, tenancy
from app.models import Council, Role, User
from app.security import hash_password

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def boss(db) -> User:
    """슈퍼 관리자 — 협의체에 속하지 않는다."""
    user = accounts.create_super(
        db, name="운영팀", email="root@ium.test", password="ium-root-2026"
    )
    assert user.council_id is None
    return user


def _login(client, email: str, password: str = "ium1234") -> None:
    client.post("/login", data={"email": email, "password": password})


# --- 서버 명령 ---------------------------------------------------------------


def test_the_super_admin_is_made_on_the_server_not_in_the_app(db):
    """화면에서 만들 길을 두지 않는다.

    앱에서 발급할 수 있게 하면 계정 하나가 새는 순간 그 사람이 협의체를 임의로 만들고
    승인할 수 있다. 그래서 명령줄뿐이고, 비밀번호도 인자로 받지 않는다.
    """
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(ROOT),
    }
    result = subprocess.run(
        [sys.executable, "-m", "app.create_super", "--email", "cli@ium.test", "--name", "운영팀"],
        cwd=ROOT, env=env, input="ium-cli-2026\n",
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "슈퍼 관리자 계정을 만들었습니다" in result.stdout

    db.expire_all()
    created = db.scalar(select(User).where(User.email == "cli@ium.test"))
    assert created.role is Role.SUPER
    assert created.council_id is None
    assert created.must_change_password is False  # 비밀번호를 본인이 정했다


def test_the_password_is_never_an_argument(db):
    """셸 기록과 프로세스 목록에 남는 자리에는 비밀번호를 두지 않는다."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "app.create_super", "--email", "x@ium.test",
         "--name", "x", "--password", "whatever"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


# --- 협의체 등록 -------------------------------------------------------------


def test_registering_a_council_does_not_open_it(db, boss):
    """등록과 승인은 다른 사건이다.

    등록은 행정 절차고, 승인은 그 동 주민이 전용 주소로 들어올 수 있게 되는 순간이다.
    """
    council = councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    assert council.is_approved is False
    with pytest.raises(Exception) as exc:
        tenancy.by_slug(db, "bono1")
    assert exc.value.status_code == 404


def test_only_the_super_admin_registers_a_council(db, seeded):
    """운영자도 매니저도 다른 동을 만들 수 없다 — 자기 협의체 안의 사람이다."""
    for key in ("member3", "member1"):
        with pytest.raises(councils.CouncilError):
            councils.register(db, seeded[key], region="안산시", dong="아무동", slug="nope")


def test_a_council_cannot_take_a_reserved_or_taken_address(db, boss):
    """주소는 한 번 알리면 바꾸기 어려워 선점과 충돌을 미리 막는다."""
    for bad in ("admin", "login", "static"):
        with pytest.raises(councils.CouncilError, match="쓸 수 없는 주소"):
            councils.register(db, boss, region="안산시", dong="아무동", slug=bad)

    with pytest.raises(councils.CouncilError, match="이미 다른 협의체"):
        councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="sunbu3")


def test_the_address_shape_is_narrow_on_purpose(db, boss):
    """한글이나 대문자를 받으면 주소가 길어지고 받아 적기 어려워진다."""
    for bad in ("선부3동", "Sunbu3", "3동", "ab", "a" * 41, "sun bu"):
        with pytest.raises(councils.CouncilError):
            councils.register(db, boss, region="안산시", dong="아무동", slug=bad)


def test_the_same_dong_cannot_be_registered_twice(db, boss):
    """자료가 둘로 갈린 다음에 합치는 일은 식별정보까지 걸려 있어 간단하지 않다."""
    with pytest.raises(councils.CouncilError, match="이미 등록"):
        councils.register(db, boss, region="안산시 단원구", dong="선부3동", slug="sunbu3-2")
    with pytest.raises(councils.CouncilError, match="이미 등록"):
        councils.register(db, boss, region="안산시 단원구 ", dong="선부3동", slug="sunbu3-3")


# --- 관리자 발급과 승인 -------------------------------------------------------


def test_a_council_without_a_manager_is_not_approved(db, boss):
    """승인하면 가입이 열린다. 가입한 분을 승인할 사람이 없으면 가입만 쌓인다 (안건 10·14)."""
    council = councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    with pytest.raises(councils.CouncilError, match="관리자를 먼저 발급"):
        councils.approve(db, boss, council)

    accounts.issue_manager(db, boss, council, name="본오1동 관리자", email="bono1@ium.test")
    councils.approve(db, boss, council)
    assert council.is_approved
    assert tenancy.by_slug(db, "bono1").dong == "본오1동"


def test_the_manager_is_a_member_with_the_flag_not_a_fourth_role(db, boss):
    """관리자를 역할로 만들지 않은 결정(안건 14)을 협의체가 늘어도 지킨다."""
    council = councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    manager, temp = accounts.issue_manager(
        db, boss, council, name="본오1동 관리자", email="bono1@ium.test"
    )
    assert manager.role is Role.MEMBER
    assert manager.is_manager is True
    assert manager.council_id == council.id
    assert manager.must_change_password is True  # 임시 비밀번호로 들어온다
    assert temp and manager.password_hash != temp  # 평문은 어디에도 저장되지 않는다


def test_a_council_has_exactly_one_manager(db, boss):
    """협의체당 한 사람 (2026-10-24 결정).

    두 사람이 되면 '누가 승인했는지' 는 기록에 남아도 '누가 승인하는 사람인지' 가
    흐려지고, 후원자가 연락할 곳도 둘이 된다.
    """
    council = councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    accounts.issue_manager(db, boss, council, name="첫 관리자", email="first@ium.test")
    with pytest.raises(accounts.AccountError, match="이미 관리자"):
        accounts.issue_manager(db, boss, council, name="둘째 관리자", email="second@ium.test")


def test_only_the_super_admin_issues_the_first_manager(db, seeded, boss):
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    with pytest.raises(accounts.AccountError, match="슈퍼 관리자만"):
        accounts.issue_manager(db, seeded["member1"], council, name="x", email="x@ium.test")


def test_suspending_a_council_keeps_the_records(db, seeded, boss):
    """중지와 파기를 구분한다 — 주소는 닫히고 기록은 보관 기간까지 남는다 (안건 09)."""
    from app.models import Case

    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    before = len(db.scalars(select(Case).where(Case.council_id == council.id)).all())
    assert before > 0

    councils.suspend(db, boss, council, "파일럿 종료")
    assert council.is_active is False
    assert len(db.scalars(select(Case).where(Case.council_id == council.id)).all()) == before
    with pytest.raises(Exception) as exc:
        tenancy.by_slug(db, "sunbu3")
    assert exc.value.status_code == 404

    councils.resume(db, boss, council)
    assert tenancy.by_slug(db, "sunbu3").is_active


def test_suspending_needs_a_reason(db, seeded, boss):
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    with pytest.raises(councils.CouncilError, match="사유"):
        councils.suspend(db, boss, council, "   ")
    assert council.is_active is True


# --- 화면 --------------------------------------------------------------------


def test_the_super_screen_shows_councils_and_nothing_inside_them(client, db, seeded, boss):
    """협의체 목록과 사람 수만 온다. 케이스도 식별정보도 오지 않는다."""
    _login(client, "root@ium.test", "ium-root-2026")
    body = client.get("/super").text

    assert "선부3동" in body
    assert "/c/sunbu3" in body
    assert "선부3동 A가정" not in body          # 비식별 코드조차 오지 않는다
    assert "홍길동" not in body                 # 식별정보는 말할 것도 없다


def test_the_super_admin_cannot_walk_into_a_council(client, db, seeded, boss):
    """슈퍼 관리자는 협의체 화면에 들어갈 수 없다.

    경계를 넘는 조회 권한이 있다는 것과, 그 동 위원의 화면을 쓸 수 있다는 것은 다르다.
    """
    _login(client, "root@ium.test", "ium-root-2026")
    for path in ("/member", "/member/donors", "/manage", "/donor"):
        body = client.get(path).text
        assert "선부3동 A가정" not in body
        assert "최세탁" not in body


def test_registering_and_opening_a_council_from_the_screen(client, db, boss):
    """등록 → 관리자 발급 → 승인. 화면에서 끊기지 않고 이어진다."""
    _login(client, "root@ium.test", "ium-root-2026")

    client.post("/super/councils", data={
        "region": "안산시 상록구", "dong": "본오1동", "slug": "bono1", "region_code": "",
    })
    council = db.scalar(select(Council).where(Council.slug == "bono1"))
    assert council is not None and not council.is_approved

    # 관리자가 없으면 승인은 안내로 막힌다
    assert "관리자를 먼저 발급" in client.post(f"/super/councils/{council.id}/approve").text

    issued = client.post(f"/super/councils/{council.id}/manager", data={
        "name": "본오1동 관리자", "email": "bono1@ium.test", "note": "",
    })
    assert "임시 비밀번호" in issued.text
    assert issued.headers.get("cache-control") == "no-store"

    client.post(f"/super/councils/{council.id}/approve")
    db.expire_all()
    assert db.scalar(select(Council).where(Council.slug == "bono1")).is_approved


def test_the_temporary_password_never_reaches_the_cookie(client, db, boss):
    """발급 응답 한 번에만 실어 보낸다. 세션에 담으면 쿠키를 타고 브라우저에 남는다."""
    _login(client, "root@ium.test", "ium-root-2026")
    client.post("/super/councils", data={
        "region": "안산시 상록구", "dong": "본오1동", "slug": "bono1", "region_code": "",
    })
    council = db.scalar(select(Council).where(Council.slug == "bono1"))
    res = client.post(f"/super/councils/{council.id}/manager", data={
        "name": "본오1동 관리자", "email": "bono1@ium.test", "note": "",
    })

    import re
    match = re.search(r'class="temp-password"[^>]*>([a-z0-9-]+)<', res.text)
    assert match, "임시 비밀번호가 화면에 없습니다"
    temp = match.group(1)
    cookie = client.cookies.get("session") or ""
    assert cookie, "세션 쿠키가 없으면 이 테스트는 아무것도 증명하지 않는다"
    assert temp not in cookie

    import base64
    padded = cookie.split(".")[0] + "=="
    assert temp.encode() not in base64.urlsafe_b64decode(padded)


def test_nobody_else_can_open_the_super_screen(client, db, seeded, boss):
    for email in ("member1@ium.test", "member1@ium.test"):
        _login(client, email)
        assert "협의체 등록" not in client.get("/super").text


# --- 협의체 전용 가입 주소 ----------------------------------------------------


def test_a_donor_signs_up_through_their_councils_address(client, db, seeded, boss):
    """후원자에게 전하는 주소다 (안건 13). 들어온 주소가 소속을 정한다."""
    council = councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    accounts.issue_manager(db, boss, council, name="관리자", email="bono1@ium.test")
    councils.approve(db, boss, council)

    form = client.get("/c/bono1/signup")
    assert "본오1동 나눔가게로" in form.text
    assert 'action="/c/bono1/signup"' in form.text

    client.post("/c/bono1/signup", data={
        "name": "본오동 사장", "phone": "010-7777-0001", "pin": "1357", "confirm": "1357",
        "shop_name": "본오분식",
    })
    donor = db.scalar(select(User).where(User.phone == "01077770001"))
    assert donor.council_id == council.id
    assert donor.shop.council_id == council.id


def test_an_unopened_councils_address_is_not_there(client, db, boss):
    """승인 전에 주소를 뿌려 주민을 받는 길을 막는다.

    404 를 그대로 띄우지 않고 안내와 함께 돌려보낸다 (app/main.py 의 핸들러). 주소를
    잘못 받아 적은 분에게 빈 404 화면을 보여 주는 것보다 낫고, 어느 쪽이든 가입 칸은
    나오지 않는다.
    """
    councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    body = client.get("/c/bono1/signup").text
    assert "찾을 수 없습니다" in body
    assert "나눔가게로 함께해 주세요" not in body   # 가입 칸이 아니라 로그인 화면이다

    client.post("/c/bono1/signup", data={
        "name": "아무개", "phone": "010-7777-0002", "pin": "1357", "confirm": "1357",
    })
    assert db.scalar(select(User).where(User.phone == "01077770002")) is None


def test_a_suspended_councils_address_closes(client, db, seeded, boss):
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    assert "나눔가게로 함께해 주세요" in client.get("/c/sunbu3/signup").text

    councils.suspend(db, boss, council, "파일럿 종료")
    body = client.get("/c/sunbu3/signup").text
    assert "나눔가게로 함께해 주세요" not in body
    assert "찾을 수 없습니다" in body


def test_the_old_address_still_works(client, db, seeded):
    """협의체가 하나였을 때 돌린 주소. 지금 지우면 이미 돌아다니는 주소가 404 가 된다."""
    res = client.get("/signup", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/c/sunbu3/signup"


def test_the_login_screen_does_not_ask_which_dong(client, db, seeded):
    """로그인은 협의체를 묻지 않는다 — 전화번호와 숫자로 사람을 찾아 소속으로 보낸다."""
    res = client.post(
        "/login", data={"phone": "010-1000-0001", "pin": "2026"}, follow_redirects=False
    )
    donor = db.scalar(select(User).where(User.phone == "01010000001"))
    if donor is not None:
        assert res.status_code == 303

    # 위원도 마찬가지다
    res = client.post(
        "/login", data={"email": "member1@ium.test", "password": "ium1234"},
        follow_redirects=False,
    )
    assert res.headers["location"] == "/member"


def test_the_super_admin_lands_on_the_council_screen(client, db, boss):
    res = client.post(
        "/login", data={"email": "root@ium.test", "password": "ium-root-2026"},
        follow_redirects=False,
    )
    assert res.headers["location"] == "/super"


def test_a_suspended_councils_people_cannot_log_in(client, db, seeded, boss):
    """협의체를 멈추면 그 안의 식별정보를 읽을 수 있는 사람도 사라진다."""
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    councils.suspend(db, boss, council, "파일럿 종료")

    res = client.post(
        "/login", data={"email": "member1@ium.test", "password": "ium1234"},
        follow_redirects=True,
    )
    assert "선부3동 A가정" not in res.text


def test_an_orphan_account_cannot_be_made_by_the_app(db, seeded):
    """위원 발급은 발급한 사람의 협의체로만 들어간다 — 소속 없는 계정이 앱에서 생기지 않는다."""
    issued, _ = accounts.issue_member(
        db, seeded["member1"], name="새 위원", email="new@ium.test"
    )
    assert issued.council_id == seeded["council"].id

    orphan = User(
        email="manual@ium.test", password_hash=hash_password("ium1234"),
        name="손으로 넣은 계정", role=Role.MEMBER,
    )
    db.add(orphan)
    db.commit()
    assert orphan.council_id is None  # DB 는 막지 않는다 (슈퍼 관리자 때문에 nullable)


def test_the_login_screen_survives_every_council_being_closed(client, db, seeded, boss):
    """협의체를 전부 중지해도 로그인 화면은 열린다.

    실제로 막힌 자리다. 로그인 화면이 운영팀 연락처를 보여 주려고 협의체의 정책을 읽고
    있었고, 중지된 협의체는 조회에서 없는 것으로 다뤄져 404 가 났다. 그 404 는 안내와
    함께 직전 화면으로 되돌리는데 직전 화면이 바로 그 화면이어서 리다이렉트가 무한히
    돌았다 — 중지를 되돌릴 슈퍼 관리자조차 들어올 수 없는 상태였다.

    오류가 나는 자리와 그 오류를 고칠 수 있는 자리가 같으면 복구할 길이 없다.
    """
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    councils.suspend(db, boss, council, "파일럿 종료")

    page = client.get("/login")
    assert page.status_code == 200
    assert "이음" in page.text

    # 그리고 슈퍼 관리자는 들어와 되돌릴 수 있다
    res = client.post(
        "/login", data={"email": "root@ium.test", "password": "ium-root-2026"},
        follow_redirects=False,
    )
    assert res.headers["location"] == "/super"
    client.post(f"/super/councils/{council.id}/resume")
    db.expire_all()
    assert db.scalar(select(Council).where(Council.slug == "sunbu3")).is_active


def test_a_failing_screen_does_not_send_you_back_to_itself(client, db, boss):
    """오류 안내는 직전 화면으로 돌아가는데, 직전 화면이 실패한 그 화면이면 돌지 않는다."""
    councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    res = client.get(
        "/c/bono1/signup",
        headers={"referer": "http://testserver/c/bono1/signup"},
        follow_redirects=False,
    )
    assert res.status_code == 303
    assert res.headers["location"] == "/"


def test_the_login_screen_names_no_dong_when_there_are_several(client, db, seeded, other_council):
    """로그인 전에는 어느 협의체인지 알 수 없다. 여러 개면 아무 동 이름도 적지 않는다."""
    body = client.get("/login").text
    assert "선부3동 지역사회보장협의체" not in body
    assert "선부2동 지역사회보장협의체" not in body
