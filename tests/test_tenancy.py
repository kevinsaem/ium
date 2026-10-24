"""협의체 경계 — 옆 동의 자료가 보이지 않는다.

테넌트 격리는 '협의체가 하나일 때' 는 증명되지 않는다. 그래서 이 파일의 테스트는 모두
선부2동을 실제로 만들고, 그 동의 위원·후원자·케이스·나눔글을 채운 뒤에 선부3동 화면을
확인한다. app/tenancy.py 의 조건을 지우면 여기가 깨진다 — 그게 이 파일의 목적이다.

"안 보인다" 를 확인하는 테스트는 조용히 무력해질 수 있다. 조건이 아니라 데이터가 없어서
통과하면 아무것도 증명하지 못한다. 그래서 어느 테스트든 먼저 '옆 동에는 분명히 있다' 를
직접 확인하고, 그다음에 '우리 화면에는 없다' 를 본다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import accounts, identity_service, matching, pilot, retention, tenancy
from app.models import (
    Case,
    Council,
    IdentityAccessLog,
    Match,
    Offer,
    OfferKind,
    OfferStatus,
    Role,
    Shop,
    User,
)
from app.security import hash_password


def _login(client, email: str, password: str = "ium1234") -> None:
    client.post("/login", data={"email": email, "password": password})


@pytest.fixture()
def neighbor(db, other_council) -> dict:
    """선부2동 — 위원 한 명, 승인된 후원자 한 명, 케이스 하나, 나눔글 하나."""
    cid = other_council.id
    member = User(
        email="member@sunbu2.test",
        password_hash=hash_password("ium1234"),
        name="선부2동 위원",
        role=Role.MEMBER,
        council_id=cid,
        is_manager=True,
        approved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    donor = User(
        phone="01099990001",
        password_hash=hash_password("2026"),
        name="선부2동 사장",
        role=Role.DONOR,
        council_id=cid,
        approved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db.add_all([member, donor])
    db.flush()

    shop = Shop(council_id=cid, owner_id=donor.id, name="선부2동 반찬집", is_certified=True)
    db.add(shop)
    db.flush()
    offer = Offer(
        council_id=cid,
        shop_id=shop.id,
        title="선부2동 김치 10포기",
        kind=OfferKind.GOODS,
        status=OfferStatus.OPEN,
    )
    case = Case(
        council_id=cid,
        code="선부2동 A가정",
        need_summary="선부2동 식료품",
        member_id=member.id,
    )
    db.add_all([offer, case])
    db.commit()
    return {
        "council": other_council,
        "member": member,
        "donor": donor,
        "shop": shop,
        "offer": offer,
        "case": case,
    }


def test_the_neighbor_council_really_has_its_own_data(db, neighbor):
    """먼저 옆 동에 자료가 있다는 것을 확인한다.

    이 테스트가 깨지면 아래의 '안 보인다' 테스트들은 전부 의미가 없다 — 데이터가 없어서
    통과하는 상태가 되기 때문이다.
    """
    assert db.scalar(select(Council).where(Council.slug == "sunbu2")) is not None
    assert db.scalar(select(Offer).where(Offer.title == "선부2동 김치 10포기")) is not None
    assert db.scalar(select(Case).where(Case.code == "선부2동 A가정")) is not None


def test_members_only_see_offers_from_their_own_council(db, seeded, neighbor):
    """매칭 후보에 옆 동 나눔글이 오르지 않는다."""
    ours = matching.open_offers_for_members(db, seeded["member1"])
    theirs = matching.open_offers_for_members(db, neighbor["member"])

    assert neighbor["offer"].id in [o.id for o in theirs]
    assert neighbor["offer"].id not in [o.id for o in ours]
    assert ours, "선부3동 후보가 비면 조건이 아니라 데이터 때문에 통과한다"


def test_the_case_list_stops_at_the_council_line(client, db, seeded, neighbor):
    """케이스 목록에 옆 동 코드가 나오지 않는다.

    이 화면은 담당 위원 조건(member_id)만으로도 이미 막힌다. 그래서 협의체 조건을
    지워도 이 테스트는 통과한다 — 경계를 증명하는 건 아래의 매칭판·후원자 목록처럼
    '협의체 전체가 보이는' 화면들이다. 그래도 남겨 둔다. 담당 조건이 언젠가 느슨해질 때
    (예: 위원끼리 케이스를 함께 보기로 하면) 경계가 바로 드러나야 하는 자리다.
    """
    _login(client, "member@sunbu2.test")
    assert "선부2동 A가정" in client.get("/member").text

    _login(client, "member1@ium.test")
    assert "선부2동 A가정" not in client.get("/member").text


def test_the_match_board_stops_at_the_council_line(client, db, seeded, neighbor):
    """매칭판은 협의체 전체를 보여 주는 화면이라 경계가 유일한 방어선이다."""
    their_match = matching.propose(
        db, neighbor["case"], neighbor["offer"], neighbor["member"], "선부2동 전달 예정"
    )
    assert their_match.council_id == neighbor["council"].id

    _login(client, "member@sunbu2.test")
    assert "선부2동 A가정" in client.get("/member/matches").text

    _login(client, "member1@ium.test")
    assert "선부2동 A가정" not in client.get("/member/matches").text


def test_the_donor_list_stops_at_the_council_line(client, db, seeded, neighbor):
    _login(client, "member@sunbu2.test")
    assert "선부2동 사장" in client.get("/member/donors").text

    _login(client, "member1@ium.test")
    assert "선부2동 사장" not in client.get("/member/donors").text


def test_a_donor_id_in_the_url_does_not_cross_the_line(client, db, seeded, neighbor):
    """목록이 막혀도 주소에 id 를 직접 넣는 길이 남는다. 그쪽도 막혀야 한다."""
    _login(client, "member1@ium.test")
    body = client.get(f"/member/donors/{neighbor['donor'].id}").text
    assert "선부2동 사장" not in body
    assert "다른 협의체" in body


def test_a_case_id_in_the_url_does_not_cross_the_line(client, db, seeded, neighbor):
    _login(client, "member1@ium.test")
    body = client.get(f"/member/cases/{neighbor['case'].id}").text
    assert "선부2동 식료품" not in body
    assert "다른 협의체" in body


def test_matching_across_councils_is_refused(db, seeded, neighbor):
    """우리 가정과 옆 동 나눔을 잇는 길은 없다.

    주소에 id 를 직접 넣으면 목록의 조건을 거치지 않는다. 한 번이라도 넘어가면 그 뒤의
    지표·월간보고서가 어느 동 것인지 알 수 없게 된다.
    """
    our_case = db.scalar(select(Case).where(Case.council_id == seeded["council"].id))
    with pytest.raises(HTTPException) as exc:
        matching.propose(db, our_case, neighbor["offer"], seeded["member1"])
    assert exc.value.status_code == 403
    assert db.scalar(select(Match)) is None


def test_the_same_case_code_can_be_used_in_two_councils(db, seeded, neighbor):
    """코드는 협의체 안에서만 유일하다.

    전역 유일로 두면 옆 동이 쓰는 코드가 '이미 사용 중' 오류로 드러난다 — 경계가 오류
    문구를 타고 새는 길이다.
    """
    db.add(
        Case(
            council_id=neighbor["council"].id,
            code="선부3동 A가정",
            need_summary="같은 코드 다른 동",
            member_id=neighbor["member"].id,
        )
    )
    db.commit()
    assert len(db.scalars(select(Case).where(Case.code == "선부3동 A가정")).all()) == 2


def test_metrics_are_counted_per_council(db, seeded, neighbor):
    """지표가 섞이면 '우리 동이 몇 건 했는지' 가 사라진다."""
    window = pilot.window(retention.current(db))
    ours = pilot.funnel(db, window, seeded["office"])
    theirs = pilot.funnel(db, window, neighbor["member"])

    assert theirs["certified_shops"] == 1
    assert ours["certified_shops"] == 1


def test_a_manager_only_unlocks_accounts_in_their_own_council(db, seeded, neighbor):
    """잠긴 계정 목록도 협의체 안이다 (안건 15의 '매니저가 해제한다')."""
    for _ in range(accounts.MAX_FAILED_LOGINS):
        accounts.record_failure(db, neighbor["donor"])
    assert accounts.is_locked(neighbor["donor"])

    assert neighbor["donor"].id in [u.id for u in accounts.locked_accounts(db, neighbor["member"])]
    assert accounts.locked_accounts(db, seeded["member1"]) == []


def test_a_member_issued_by_a_council_belongs_to_it(db, seeded, neighbor):
    """위원 발급은 발급한 사람의 협의체로 들어간다."""
    issued, _ = accounts.issue_member(
        db, neighbor["member"], name="새 위원", email="new@sunbu2.test"
    )
    assert issued.council_id == neighbor["council"].id


def test_a_donor_registered_by_a_member_belongs_to_that_council(db, seeded, neighbor):
    donor, _ = accounts.register_donor(
        db, neighbor["member"], name="새 사장", phone="010-9999-0002", shop_name="새 가게"
    )
    assert donor.council_id == neighbor["council"].id
    assert donor.shop.council_id == neighbor["council"].id


def test_an_account_without_a_council_is_refused_not_emptied(db, seeded):
    """소속이 없는 계정은 빈 목록이 아니라 거절이다.

    빈 화면으로 보여 주면 '자료가 없다' 와 '경계가 깨졌다' 를 구별할 수 없다.
    """
    orphan = User(
        email="orphan@ium.test",
        password_hash=hash_password("ium1234"),
        name="소속 없음",
        role=Role.MEMBER,
    )
    db.add(orphan)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        tenancy.scoped(select(Case), Case, orphan)
    assert exc.value.status_code == 403


def test_an_unapproved_council_cannot_be_resolved(db):
    """승인 전 협의체는 없는 것으로 다룬다 — 주소만 뿌려 주민을 받는 길을 막는다."""
    db.add(Council(slug="waiting", region="안산시 상록구", dong="본오1동"))
    db.commit()
    with pytest.raises(HTTPException) as exc:
        tenancy.by_slug(db, "waiting")
    assert exc.value.status_code == 404
    assert tenancy.by_slug(db, "waiting", approved_only=False).dong == "본오1동"


def test_the_identity_access_log_belongs_to_the_data_not_the_reader(db, seeded, neighbor):
    """열람 기록은 읽은 사람이 아니라 읽힌 자료의 협의체에 남는다.

    행위자 기준으로 남기면, 경계를 넘는 열람이 생겼을 때 그 기록이 엉뚱한 동에 쌓여
    감사가 끊긴다.
    """
    case = db.scalar(select(Case).where(Case.council_id == seeded["council"].id))
    identity_service.read_identity(db, case, seeded["member1"], reason="전달 전 주소 확인")

    log = db.scalar(select(IdentityAccessLog).order_by(IdentityAccessLog.id.desc()))
    assert log.council_id == case.council_id


def test_the_super_admin_can_never_read_identity(db):
    """슈퍼 관리자는 협의체를 늘리는 권한이지, 그 안을 들여다보는 권한이 아니다.

    경계를 넘을 수 있는 유일한 역할이라 가장 쉽게 넓어진다. 표(app/permissions.py)에
    한 줄만 더해도 조용히 넓어지므로 여기서 고정한다.
    """
    from app import permissions

    assert permissions.can(Role.SUPER, "council", "write")
    for resource in ("case", "case_identity", "match", "audit_log", "account_log"):
        assert not permissions.can(Role.SUPER, resource), resource
        assert not permissions.can(Role.SUPER, resource, "write"), resource


def test_the_super_admin_sees_across_councils(db, seeded, neighbor):
    """경계를 넘는 조회는 슈퍼 관리자만 가능하다 — 식별정보가 아닌 운영 자료에서."""
    boss = User(
        email="root@ium.test",
        password_hash=hash_password("ium1234"),
        name="슈퍼 관리자",
        role=Role.SUPER,
    )
    db.add(boss)
    db.commit()

    all_cases = db.scalars(tenancy.scoped(select(Case), Case, boss)).all()
    codes = {c.code for c in all_cases}
    assert "선부2동 A가정" in codes
    assert "선부3동 A가정" in codes


def test_the_donor_feed_stops_at_the_council_line(client, db, seeded, neighbor):
    """후원자 피드의 '동네' 는 자기 협의체다.

    실제 서버에서 처음 발견한 구멍이다. 테스트는 다 통과하는데 후원자 홈에 선부2동
    가게의 나눔이 섞여 있었다. 후원자는 그걸 자기 동네 이야기로 읽고, 보고 가게를
    찾아갈 수도 있다.
    """
    _login(client, "blue@ium.test")
    body = client.get("/donor").text
    assert "선부2동 김치 10포기" not in body
    assert "이불 빨래 무료 세탁" in body, "우리 동 나눔이 비면 조건이 아니라 데이터 때문에 통과한다"


def test_an_offer_id_in_the_url_does_not_cross_the_line(client, db, seeded, neighbor):
    _login(client, "blue@ium.test")
    body = client.get(f"/donor/offers/{neighbor['offer'].id}").text
    assert "선부2동 김치 10포기" not in body
    assert "다른 협의체" in body


def test_the_header_shows_the_viewers_own_dong(client, db, seeded, neighbor):
    """화면에 적히는 동 이름은 설정값이 아니라 그 사람의 협의체다."""
    _login(client, "member@sunbu2.test")
    assert "선부2동" in client.get("/member").text

    _login(client, "member1@ium.test")
    body = client.get("/member").text
    assert "선부3동" in body


# --- 주소에 id 를 직접 넣는 길 -------------------------------------------------
#
# 목록은 협의체로 걸러진다. 문제는 그 목록을 거치지 않는 길이다. 새 협의체의 관리자가
# /member/donors/<옆 동 후원자 id>/approve 로 옆 동 후원자를 승인할 수 있었다. 실제
# 서버에서 사슬을 끝까지 걸어 보다가 나왔고, 테스트는 전부 통과하고 있었다.
#
# 그래서 라우트별로 확인을 붙이는 대신 조회를 헬퍼로 모았다. 아래 테스트는 그 헬퍼를
# 우회하는 라우트가 새로 생기면 깨진다.


def _manager_of_neighbor(client, neighbor):
    client.post("/login", data={"email": "member@sunbu2.test", "password": "ium1234"})


def test_a_manager_cannot_approve_a_donor_across_the_line(client, db, seeded, neighbor):
    """승인은 매니저 권한이지만, 자기 협의체 안에서만이다 (안건 10·14)."""
    waiting = User(
        phone="01088880001",
        password_hash=hash_password("2026"),
        name="선부3동 대기자",
        role=Role.DONOR,
        council_id=seeded["council"].id,
    )
    db.add(waiting)
    db.commit()

    _manager_of_neighbor(client, neighbor)
    body = client.post(f"/member/donors/{waiting.id}/approve").text
    db.expire_all()

    assert "다른 협의체" in body
    assert db.get(User, waiting.id).approved_at is None


def test_every_manager_action_stops_at_the_line(client, db, seeded, neighbor):
    """승인·승인취소·메모·잠금해제 — 대상이 옆 동이면 전부 막힌다."""
    ours = seeded["donor"]
    _manager_of_neighbor(client, neighbor)

    assert "다른 협의체" in client.post(f"/member/donors/{ours.id}/approve").text
    assert "다른 협의체" in client.post(
        f"/member/donors/{ours.id}/unapprove", data={"reason": "아무 이유"}
    ).text
    assert "다른 협의체" in client.post(
        f"/member/donors/{ours.id}/notes", data={"body": "남의 동 메모"}
    ).text
    assert "다른 협의체" in client.post(f"/member/manage/unlock/{ours.id}").text

    from app.models import DonorNote

    db.expire_all()
    assert db.get(User, ours.id).approved_at is not None   # 승인 취소가 걸리지 않았다
    assert db.get(User, ours.id).locked_at is None         # 잠금 해제도 손대지 못했다
    assert db.scalars(select(DonorNote).where(DonorNote.donor_id == ours.id)).all() == []


def test_a_member_cannot_match_a_neighbors_offer_through_the_url(client, db, seeded, neighbor):
    """케이스는 우리 것, 나눔글은 옆 동 — 매칭 라우트에서 막힌다."""
    from app.models import Match

    case = db.scalar(select(Case).where(Case.council_id == seeded["council"].id))
    _login(client, "member1@ium.test")
    body = client.post(
        "/member/matches",
        data={"case_id": str(case.id), "offer_id": str(neighbor["offer"].id), "note": ""},
    ).text

    assert "다른 협의체" in body
    assert db.scalar(select(Match)) is None


def test_the_office_screens_stop_at_the_line(client, db, seeded, neighbor):
    """운영자 동작도 자기 협의체 안이다 — 위원 위촉 해제·비밀번호 초기화·가게 인증."""
    other_member = neighbor["member"]
    _login(client, "office@ium.test")

    assert "다른 협의체" in client.post(f"/office/members/{other_member.id}/reset").text
    assert "다른 협의체" in client.post(f"/office/members/{other_member.id}/toggle").text
    assert "다른 협의체" in client.post(
        f"/office/members/{other_member.id}/manager", data={"grant": "1"}
    ).text
    assert "다른 협의체" in client.post(f"/office/shops/{neighbor['shop'].id}/certify").text

    db.expire_all()
    assert db.get(User, other_member.id).is_active is True
    assert neighbor["shop"].is_certified is True  # 이미 인증된 상태가 바뀌지 않았다
