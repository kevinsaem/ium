"""매니저 권한 테스트.

위원회 결정(2026-10-17, 안건 14): "위원 중 한 명이 매니저 역할을 맡으며" 운영진인 케빈이
맡는다. 그래서 매니저는 네 번째 역할이 아니라 위원에게 주는 권한이다.

누가 맡을지는 정례회의에서 정하고 운영자가 화면에서 반영한다 — 매니저가 스스로 다른
사람에게 넘길 수는 없다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import permissions
from app.models import AccountEvent, Role, User
from app.permissions import MANAGER_RESOURCES, is_manager, manager_can


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _grant(client, member_id: int, grant: bool = True):
    return client.post(
        f"/office/members/{member_id}/manager",
        data={"grant": "1" if grant else ""},
        follow_redirects=True,
    )


# --- 매니저는 역할이 아니다 ---------------------------------------------------


def test_manager_is_not_a_role_of_its_own():
    """매니저는 역할이 아니라 위원에게 주는 권한이다 (위원회 결정, 안건 14).

    역할을 늘리면 권한 표가 한 줄 늘고 사전 승인에서 설명할 것도 늘어난다. 그래서
    매니저를 역할로 만들지 않았다. 지금 역할은 넷이고, 그중 앞의 셋은 한 협의체 안에서
    성립한다 — 슈퍼 관리자만 그 경계 밖이다 (2026-10-24 결정).
    """
    assert {r.value for r in Role} == {"donor", "member", "office", "super"}
    assert "manager" not in {r.value for r in Role}
    assert {r.value for r in Role if r.is_scoped} == {"donor", "member", "office"}


def test_the_seeded_manager_is_one_member_not_all(db, seeded):
    """매니저는 위원 중 '한 명'이다. 모든 위원이 가지면 권한을 나눈 의미가 없다."""
    assert is_manager(seeded["member1"])        # 시드에서 지정한 매니저
    assert not is_manager(seeded["member2"])    # 같은 위원이지만 매니저는 아니다


def test_only_a_member_can_be_a_manager(db, seeded):
    """운영자나 후원자에게 플래그가 켜져도 매니저가 되지는 않는다."""
    for key in ("office", "donor"):
        seeded[key].is_manager = True
        db.commit()
        assert not is_manager(seeded[key])


def test_an_unappointed_member_loses_manager_authority(db, seeded):
    """위촉이 해제되면 매니저 권한도 함께 멈춘다."""
    member = seeded["member1"]
    assert is_manager(member)

    member.is_active = False
    db.commit()
    assert not is_manager(member)


@pytest.mark.parametrize("resource", sorted(MANAGER_RESOURCES))
def test_manager_resources_need_the_flag(db, seeded, resource):
    member = seeded["member2"]  # 매니저가 아닌 위원
    assert not manager_can(member, resource)

    member.is_manager = True
    db.commit()
    assert manager_can(member, resource)


def test_unknown_resource_is_refused_even_for_a_manager(db, seeded):
    assert not manager_can(seeded["member1"], "아무거나")


# --- 지정과 해제 -------------------------------------------------------------


def test_office_grants_and_revokes_manager_authority(db, seeded, client):
    member = seeded["member2"]
    _login(client, "office@ium.test")

    body = _grant(client, member.id).text
    assert "매니저 권한을 부여" in body
    db.expire_all()
    assert db.get(User, member.id).is_manager is True

    body = _grant(client, member.id, grant=False).text
    assert "매니저 권한을 해제" in body
    db.expire_all()
    assert db.get(User, member.id).is_manager is False


def test_granting_is_recorded_as_a_meeting_decision(db, seeded, client):
    """매니저가 바뀐 것은 정례회의 결정이다. 조용히 바뀌면 안 된다."""
    member = seeded["member2"]
    _login(client, "office@ium.test")
    _grant(client, member.id)

    event = db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == member.id, AccountEvent.action == "grant_manager"
        )
    )
    assert event is not None
    assert event.actor_id == seeded["office"].id
    assert "정례회의" in event.note


def test_a_manager_cannot_hand_the_role_to_someone_else(db, seeded, client):
    """매니저 지정은 운영자가 정례회의 결정을 반영하는 경로뿐이다."""
    other = seeded["member2"]

    _login(client, "member1@ium.test")  # 매니저 본인
    res = client.post(
        f"/office/members/{other.id}/manager", data={"grant": "1"}, follow_redirects=False
    )

    assert res.headers["location"] == "/"
    db.expire_all()
    assert db.get(User, other.id).is_manager is False


def test_granting_to_a_non_member_is_refused(db, seeded, client):
    _login(client, "office@ium.test")
    for key in ("office", "donor"):
        body = _grant(client, seeded[key].id).text
        assert "위원을 찾을 수 없습니다" in body


def test_members_screen_shows_who_the_manager_is(db, seeded, client):
    _login(client, "office@ium.test")
    body = client.get("/office/members").text
    assert "매니저 권한 해제" in body   # 시드 매니저(member1) 쪽
    assert "매니저 권한 부여" in body   # 매니저가 아닌 위원 쪽


def test_permission_matrix_lists_the_manager_duties(db, seeded, client):
    """위원회에 보여 주는 표에 매니저 몫이 드러나야 한다."""
    _login(client, "office@ium.test")
    html = client.get("/office").text

    for resource in MANAGER_RESOURCES:
        assert resource in html, resource
    assert "위원(매니저)" in html


def test_describe_keeps_roles_and_manager_rows_apart(db):
    rows = {r["resource"]: r for r in permissions.describe()}
    assert rows["case_identity"]["read"] == "위원"
    assert rows["donor_approval"]["write"] == "위원(매니저)"
