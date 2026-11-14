"""첫 화면과 협의체 전용 주소 — 사람이 들어오는 입구.

전에는 `/` 가 로그인으로 바로 보냈다. 로그인 화면은 이미 아는 사람을 위한 자리고, 카톡으로
링크를 받아 처음 눌러 본 가게 사장님은 "이음이 뭔가" 를 모른 채 로그인 칸만 보고 닫는다.

그래서 입구가 둘 있다.

    /               앱 소개 → 가입 또는 로그인
    /c/<slug>       그 동 이름으로 소개 → 그 협의체 가입

이 파일은 두 입구가 열려 있는지, 그리고 **소개를 보기 전에 전화번호를 적게 되지 않는지**
를 고정한다. 링크를 받은 분이 먼저 보는 것이 입력 칸이면, 무엇에 가입하는지 모르는 채로
개인정보를 적게 된다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app import councils, invites
from app.models import Council, Role, User
from app.security import hash_password


@pytest.fixture()
def boss(db) -> User:
    from app import accounts

    return accounts.create_super(
        db, name="운영팀", email="root@ium.test", password="ium-root-2026"
    )


# --- 첫 화면 ----------------------------------------------------------------


def test_the_front_door_explains_before_it_asks(client, db, seeded):
    """소개가 먼저고 입력 칸은 다음이다."""
    body = client.get("/").text

    assert "가게에 남는 것이" in body          # 무엇을 하는 앱인가
    assert "위원이 찾아 연결합니다" in body     # 어떻게 이어지나
    assert 'name="phone"' not in body          # 전화번호 칸은 여기 없다
    assert 'name="pin"' not in body


def test_the_front_door_says_the_principle_out_loud(client, db, seeded):
    """도움받는 분이 앱에 등장하지 않는다는 것이 첫 화면에 적혀 있어야 한다.

    이 앱의 전부가 그 한 줄에 걸려 있다. 후원자가 "내가 누구를 돕는지 알 수 있나" 를
    물을 자리가 가입 전이고, 그 답이 화면에 없으면 묻지 않은 채로 가입한다.
    """
    body = client.get("/").text
    assert "도움받는 분은 이 앱에 등장하지 않습니다" in body
    assert "담당 위원 한 사람만" in body


def test_the_front_door_leads_to_the_pilot_councils_signup(client, db, seeded):
    """협의체가 하나뿐이면 그 동 가입으로 보낸다."""
    body = client.get("/").text
    assert 'href="/c/sunbu3/signup"' in body
    assert 'href="/login"' in body
    assert "선부3동" in body


def test_the_front_door_names_no_dong_when_there_are_several(
    client, db, seeded, other_council
):
    """어느 동인지 모르는 채로 가입시킬 수는 없다.

    협의체가 여럿이면 동 이름을 적지 않고, 가입은 전용 주소로 들어온 사람만 하게 한다 —
    아무 동으로나 보내면 선부2동 사장님이 선부3동 후원자가 된다.
    """
    body = client.get("/").text
    assert "선부3동 지역사회보장협의체" not in body
    assert 'href="/c/sunbu3/signup"' not in body
    assert 'href="/login"' in body


def test_someone_logged_in_goes_to_their_own_screen(client, db, seeded):
    """소개는 처음 오는 사람을 위한 것이다. 쓰던 사람은 자기 화면으로."""
    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    res = client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/member"


# --- 협의체 전용 주소 --------------------------------------------------------


def test_the_councils_address_speaks_in_its_own_dong(client, db, seeded):
    """관리자가 후원자에게 전하는 바로 그 주소다."""
    body = client.get("/c/sunbu3").text

    assert "선부3동 나눔가게로 함께해 주세요" in body
    assert "선부3동 위원이 직접 전달합니다" in body
    assert 'href="/c/sunbu3/signup"' in body
    assert 'name="phone"' not in body   # 여기서도 소개가 먼저다


def test_the_councils_address_does_not_promise_what_it_cannot(client, db, seeded):
    """전달됐다는 것만 알려 준다 — 어느 가정인지는 알려 주지 않는다."""
    body = client.get("/c/sunbu3").text
    assert "어느 가정인지는 알려 드리지 않습니다" in body
    assert "후원자에게 공개되지 않습니다" in body


def test_an_unopened_councils_address_is_not_there(client, db, boss):
    """승인 전 협의체의 주소는 소개도 보여 주지 않는다."""
    councils.register(db, boss, region="안산시 상록구", dong="본오1동", slug="bono1")
    body = client.get("/c/bono1").text
    assert "찾을 수 없습니다" in body
    assert "본오1동 나눔가게로" not in body


def test_a_suspended_councils_address_closes(client, db, seeded, boss):
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    assert "선부3동 나눔가게로" in client.get("/c/sunbu3").text

    councils.suspend(db, boss, council, "파일럿 종료")
    assert "선부3동 나눔가게로" not in client.get("/c/sunbu3").text


def test_the_dong_in_the_address_is_the_one_you_signed_up_for(client, db, seeded, boss):
    """옆 동 주소로 들어오면 옆 동 소개를 보고 옆 동 후원자가 된다."""
    other = councils.register(db, boss, region="안산시 단원구", dong="선부2동", slug="sunbu2")
    from app import accounts

    accounts.issue_manager(db, boss, other, name="선부2동 관리자", email="mg2@ium.test")
    councils.approve(db, boss, other)

    assert "선부2동 나눔가게로 함께해 주세요" in client.get("/c/sunbu2").text

    client.post(
        "/c/sunbu2/signup",
        data={"name": "선부2동 사장", "phone": "010-2222-0001", "pin": "1357",
              "confirm": "1357", "shop_name": "선부2동 분식"},
    )
    donor = db.scalar(select(User).where(User.phone == "01022220001"))
    assert donor.council_id == other.id


# --- 초대 링크에 코드 담기 ---------------------------------------------------


def test_the_invite_link_fills_the_code_in(client, db, seeded):
    """관리자가 보내는 링크에 코드가 들어 있으면 받은 분이 손으로 적지 않는다.

    오타로 실패하는 일이 사라지니, 그 때문에 대기에 걸릴 일도 함께 줄어든다.
    """
    code = invites.create(db, seeded["member1"], days=14, max_uses=1)
    body = client.get(f"/c/sunbu3/join?code={code.code}").text
    assert f'name="code" value="{code.code}"' in body


def test_a_loosely_typed_code_in_the_link_still_fills_in(client, db, seeded):
    """소문자나 하이픈이 섞인 링크도 같은 코드로 읽는다."""
    code = invites.create(db, seeded["member1"], days=14, max_uses=1)
    sloppy = code.code.lower()[:4] + "-" + code.code.lower()[4:]
    body = client.get(f"/c/sunbu3/join?code={sloppy}").text
    assert f'name="code" value="{code.code}"' in body


def test_the_code_field_stays_for_people_without_the_link(client, db, seeded):
    """링크 없이 코드만 받아 적어 온 분도 들어올 수 있어야 한다."""
    body = client.get("/c/sunbu3/join").text
    assert 'name="code" value=""' in body


def test_a_link_with_a_wrong_code_does_not_count_as_a_failure(client, db, seeded):
    """화면을 열어 본 것만으로는 실패가 아니다 — 눌러 보기만 해도 대기가 걸리면 안 된다."""
    client.get("/c/sunbu3/join?code=WRONGXYZ")
    client.get("/c/sunbu3/join?code=ALSOWRNG")

    db.expire_all()
    council = db.scalar(select(Council).where(Council.slug == "sunbu3"))
    assert council.join_failed_attempts == 0


# --- 전달 수단 (관리 화면) ----------------------------------------------------


def test_the_manager_gets_both_addresses_to_copy(client, db, seeded):
    """후원자용과 위원용 — 관리자가 그대로 복사해 보낼 수 있어야 한다."""
    code = invites.create(db, seeded["member1"], days=14, max_uses=3)
    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    body = client.get("/manage/people").text

    assert "http://testserver/c/sunbu3" in body
    assert f"http://testserver/c/sunbu3/join?code={code.code}" in body
    assert "data-copy-btn" in body
    assert "data-qr" in body


def test_the_donor_address_is_said_to_be_shareable(client, db, seeded):
    """가게에 붙여도 되는 주소와, 단체 대화방에 올리면 안 되는 주소를 구분해 말해 준다."""
    invites.create(db, seeded["member1"], days=14, max_uses=1)
    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    body = client.get("/manage/people").text

    assert "비밀이 아닙니다" in body                    # 후원자용
    assert "코드가 들어 있습니다" in body                # 위원용


def test_a_revoked_code_offers_no_link(client, db, seeded):
    """못 쓰는 코드의 링크를 남겨 두면 그걸 보낸다."""
    code = invites.create(db, seeded["member1"], days=14, max_uses=1)
    invites.revoke(db, seeded["member1"], code)

    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    body = client.get("/manage/people").text
    assert f"join?code={code.code}" not in body


def test_the_qr_is_drawn_in_the_browser_not_fetched(client, db, seeded):
    """위원용 링크에는 초대 코드가 들어 있다.

    QR 이미지를 외부 서비스에서 받아 오면 그 코드를 남의 서버에 넘기는 셈이다. 그래서
    브라우저 안에서 그린다 — 이 테스트는 이미지 주소를 외부로 만들어 두지 않았는지를 본다.
    """
    invites.create(db, seeded["member1"], days=14, max_uses=1)
    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    body = client.get("/manage/people").text

    for leaky in ("chart.googleapis.com", "qrserver.com", "qrickit", "goqr.me"):
        assert leaky not in body, leaky


# --- 모바일 ------------------------------------------------------------------


def test_every_entrance_is_built_for_a_phone(client, db, seeded):
    """완료 기준이 "휴대폰에서 끝까지" 다. 입구부터 그래야 한다."""
    for path in ("/", "/c/sunbu3", "/c/sunbu3/signup", "/c/sunbu3/join", "/login"):
        body = client.get(path).text
        assert "width=device-width" in body, path
        assert 'class="phone"' in body, path


def test_the_whole_donor_path_works_from_the_address(client, db, seeded):
    """전용 주소로 들어와 가입하고 나눔글을 올리는 흐름이 끝까지 된다 (4단계 완료 기준)."""
    landing = client.get("/c/sunbu3")
    assert landing.status_code == 200

    signed_up = client.post(
        "/c/sunbu3/signup",
        data={"name": "새 사장", "phone": "010-3333-0001", "pin": "2468",
              "confirm": "2468", "shop_name": "새 분식", "address": "안산시 단원구 선부동 1-1"},
    )
    donor = db.scalar(select(User).where(User.phone == "01033330001"))
    assert donor is not None and donor.council_id == seeded["council"].id

    # 가입하면 바로 들어와 있고, 가입됐다는 말이 그 화면에 뜬다.
    #
    # 이 한 줄이 없으면 가입하신 분이 아무 안내 없이 낯선 화면을 본다. 실제로 그랬다 —
    # 안내를 session["flash"] 에 넣었는데 _start_session 의 session.clear() 가 지웠다.
    # 안내는 리다이렉트를 따라간 그 응답에만 실린다. 다음 화면에서 찾으면 이미 소비됐다.
    assert '<div class="flash">새 사장님, 가입했습니다.' in signed_up.text

    assert client.get("/donor/post").status_code == 200
    client.post(
        "/donor/offers",
        data={"title": "김치 5포기", "kind": "goods", "quantity_note": "5포기",
              "delivery": "member_pickup", "detail": ""},
    )
    from app.models import Offer

    offer = db.scalar(select(Offer).where(Offer.title == "김치 5포기"))
    assert offer is not None
    assert offer.council_id == seeded["council"].id

    # 승인 전이라 위원의 후보에는 아직 오르지 않는다 (안건 10)
    from app import matching

    assert offer.id not in [o.id for o in matching.open_offers_for_members(db, seeded["member1"])]


def test_a_member_joins_from_the_link_end_to_end(client, db, seeded):
    """위원도 링크 하나로 끝까지 — 받은 링크를 눌러 가입하고 관리자가 승인한다."""
    code = invites.create(db, seeded["member1"], days=14, max_uses=1)

    form = client.get(f"/c/sunbu3/join?code={code.code}")
    assert form.status_code == 200
    client.post(
        f"/c/sunbu3/join?code={code.code}",
        data={"code": code.code, "name": "링크 위원", "email": "link@ium.test",
              "password": "ium-link-2026", "confirm": "ium-link-2026"},
    )
    member = db.scalar(select(User).where(User.email == "link@ium.test"))
    assert member is not None and member.is_approved is False

    client.post("/login", data={"email": "member1@ium.test", "password": "ium1234"})
    client.post(f"/manage/members/{member.id}/approve")

    db.expire_all()
    assert db.get(User, member.id).is_approved is True

    client.post("/login", data={"email": "link@ium.test", "password": "ium-link-2026"})
    assert "선부3동 A가정" in client.get("/member").text


def test_an_account_without_a_council_is_told_so_not_looped(client, db, seeded):
    """소속 없는 계정은 무한 리다이렉트가 아니라 문장을 본다.

    역할 홈의 조회가 '소속 협의체가 없는 계정입니다' 로 막고, 그 안내가 홈으로 되돌리고,
    홈이 다시 역할 홈으로 보내 브라우저가 멈췄다. 승인 대기에서 겪은 것과 같은 고리다 —
    오류가 나는 자리와 그 오류를 벗어날 자리가 같으면 나갈 길이 없다.
    """
    orphan = User(
        email="orphan@ium.test",
        password_hash=hash_password("ium1234"),
        name="소속 없음",
        role=Role.MEMBER,
        approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(orphan)
    db.commit()

    client.post("/login", data={"email": "orphan@ium.test", "password": "ium1234"})
    page = client.get("/")   # 돌면 여기서 터진다
    assert page.status_code == 200
    assert "소속 협의체가 없습니다" in page.text
    assert "선부3동 A가정" not in page.text
