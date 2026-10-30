"""관리자 권한 테스트.

위원회 결정(2026-10-17, 안건 14): "위원 중 한 명이 매니저 역할을 맡으며" 운영진인 케빈이
맡는다. 그래서 관리자는 역할이 아니라 위원에게 주는 권한이다.

운영자 역할을 폐기하면서(2026-10-24 결정) 운영자가 하던 일이 전부 관리자에게 왔다.
협의체당 한 사람이고, 넘기는 길이 둘 있다 — 관리자가 직접 넘기거나 슈퍼 관리자가 교체한다.
한쪽만으로는 공백이 생긴다. 관리자가 연락이 안 되면 협의체가 멈추고, 슈퍼 관리자만
가능하면 위원들이 스스로 정할 수 없다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import permissions
from app.models import AccountEvent, Role, User
from app.permissions import MANAGER_RESOURCES, is_manager, manager_can


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _hand_over(client, member_id: int):
    """관리자를 다른 위원에게 넘긴다. 넘기면 본인 권한이 사라진다."""
    return client.post(f"/manage/members/{member_id}/manager", follow_redirects=True)


# --- 관리자는 역할이 아니다 ---------------------------------------------------


def test_manager_is_not_a_role_of_its_own():
    """매니저는 역할이 아니라 위원에게 주는 권한이다 (위원회 결정, 안건 14).

    역할을 늘리면 권한 표가 한 줄 늘고 사전 승인에서 설명할 것도 늘어난다. 운영자 역할을
    폐기한 것도 같은 이유다 — 그 일이 전부 관리자에게 오면서 역할로 둘 근거가 사라졌다.

    역할은 셋이다. 앞의 둘은 한 협의체 안에서 성립하고 슈퍼 관리자만 그 경계 밖이다.
    """
    assert {r.value for r in Role} == {"donor", "member", "super"}
    assert "manager" not in {r.value for r in Role}
    assert "office" not in {r.value for r in Role}
    assert {r.value for r in Role if r.is_scoped} == {"donor", "member"}


def test_the_seeded_manager_is_one_member_not_all(db, seeded):
    """매니저는 위원 중 '한 명'이다. 모든 위원이 가지면 권한을 나눈 의미가 없다."""
    assert is_manager(seeded["member1"])        # 시드에서 지정한 매니저
    assert not is_manager(seeded["member2"])    # 같은 위원이지만 매니저는 아니다


def test_only_a_member_can_be_a_manager(db, seeded):
    """후원자에게 플래그가 켜져도 관리자가 되지는 않는다."""
    seeded["donor"].is_manager = True
    db.commit()
    assert not is_manager(seeded["donor"])


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


def test_handing_over_moves_the_role_and_does_not_copy_it(db, seeded, client):
    """협의체당 한 사람이다. 넘기면 본인 권한이 사라진다.

    '부여/해제' 를 따로 두지 않은 이유다 — 두 사람이 관리자인 상태나 아무도 관리자가
    아닌 상태를 만들 수 있고, 뒤쪽은 그 협의체가 아무것도 못 하게 되는 상태다.
    """
    manager, successor = seeded["member1"], seeded["member2"]
    _login(client, "member1@ium.test")

    body = _hand_over(client, successor.id).text
    assert "넘겼습니다" in body

    db.expire_all()
    assert db.get(User, successor.id).is_manager is True
    assert db.get(User, manager.id).is_manager is False


def test_after_handing_over_the_manage_screen_closes(db, seeded, client):
    """넘긴 사람에게 관리 화면이 계속 열려 있으면 두 사람이 관리자인 셈이다."""
    _login(client, "member1@ium.test")
    _hand_over(client, seeded["member2"].id)

    assert client.get("/manage/people", follow_redirects=False).headers["location"] == "/"

    _login(client, "member2@ium.test")
    assert "관리자 화면" in client.get("/manage/people").text


def test_handing_over_is_recorded_on_both_sides(db, seeded, client):
    """관리자가 바뀐 것은 조용히 지나갈 일이 아니다. 받은 쪽과 넘긴 쪽에 모두 남는다."""
    manager, successor = seeded["member1"], seeded["member2"]
    successor_name = successor.name
    _login(client, "member1@ium.test")
    _hand_over(client, successor.id)

    got = db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == successor.id, AccountEvent.action == "grant_manager"
        )
    )
    gave = db.scalar(
        select(AccountEvent).where(
            AccountEvent.user_id == manager.id, AccountEvent.action == "revoke_manager"
        )
    )
    assert got is not None and got.actor_id == manager.id
    assert gave is not None and successor_name in gave.note


def test_a_plain_member_cannot_make_themselves_manager(db, seeded, client):
    """관리 화면 자체가 관리자에게만 열린다. 넘기는 길도 그 안에만 있다."""
    other_id = seeded["member2"].id
    _login(client, "member2@ium.test")
    res = client.post(f"/manage/members/{other_id}/manager", follow_redirects=False)

    assert res.headers["location"] == "/"
    db.expire_all()
    assert db.get(User, other_id).is_manager is False


def test_handing_over_to_a_pending_or_unappointed_member_is_refused(db, seeded, client):
    """승인되지 않았거나 위촉이 해제된 위원에게 넘기면 관리자가 없는 협의체가 된다."""
    successor = seeded["member2"]
    _login(client, "member1@ium.test")

    successor.is_active = False
    db.commit()
    assert "위촉이 해제된" in _hand_over(client, successor.id).text

    successor.is_active = True
    successor.approved_at = None
    db.commit()
    assert "먼저 승인" in _hand_over(client, successor.id).text

    db.expire_all()
    assert db.get(User, seeded["member1"].id).is_manager is True


def test_handing_over_to_a_donor_is_refused(db, seeded, client):
    _login(client, "member1@ium.test")
    body = _hand_over(client, seeded["donor"].id).text
    assert "위원을 찾을 수 없습니다" in body


def test_the_manage_screen_shows_who_the_manager_is(db, seeded, client):
    _login(client, "member1@ium.test")
    body = client.get("/manage/people").text
    assert "이관희 위원" in body
    assert "관리자" in body


def test_permission_matrix_lists_the_manager_duties(db, seeded, client):
    """위원회에 보여 주는 표에 관리자 몫이 드러나야 한다."""
    _login(client, "member1@ium.test")
    html = client.get("/manage").text

    for resource in MANAGER_RESOURCES:
        assert resource in html, resource
    assert "관리자" in html


def test_the_table_says_who_reads_identity_and_it_is_not_the_manager(db):
    """표의 기준을 역할에서 행위자로 바꾼 이유가 이 한 줄이다.

    역할 기준 표로는 '위원' 까지만 적을 수 있었고, '그 가정의 담당 위원' 이라는 실제
    조건은 코드에만 있었다. 표가 실제보다 넓게 보였다.
    """
    rows = {r["resource"]: r for r in permissions.describe()}
    assert rows["case_identity"]["read"] == "담당 위원"
    assert rows["case_identity"]["write"] == "담당 위원"
    assert rows["donor_approval"]["write"] == "관리자"
    assert rows["identity_retention"]["write"] == "관리자"
    assert rows["council"]["write"] == "슈퍼 관리자"
