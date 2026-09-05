"""운영자 흐름 테스트 — 위촉 해제와 케이스 인계.

담당 케이스를 남긴 채 위원을 해제하면 그 가정은 아무도 손댈 수 없게 된다. 담당 위원만
식별정보를 열 수 있고, 담당 위원만 매칭을 취소·전달할 수 있기 때문이다. 복구 경로가
없는 상태이므로 해제 자체를 막고 인계를 먼저 시킨다.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.models import Case, CaseStatus, IdentityAccessLog, User


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _open_case_count(db, member_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Case)
        .where(Case.member_id == member_id, Case.status != CaseStatus.CLOSED)
    )


def test_cannot_deactivate_a_member_holding_live_cases(db, seeded, client):
    member1 = seeded["member1"]
    assert _open_case_count(db, member1.id) == 3

    _login(client, "office@ium.test")
    body = client.post(f"/office/members/{member1.id}/toggle", follow_redirects=True).text

    assert "미종결 케이스 3건이 있습니다" in body
    db.expire_all()
    assert db.get(User, member1.id).is_active is True


def test_handover_moves_cases_and_unblocks_deactivation(db, seeded, client):
    member1, member2 = seeded["member1"], seeded["member2"]

    _login(client, "office@ium.test")
    client.post(
        f"/office/members/{member1.id}/handover", data={"to_member_id": str(member2.id)}
    )

    db.expire_all()
    assert _open_case_count(db, member1.id) == 0
    assert _open_case_count(db, member2.id) == 3

    client.post(f"/office/members/{member1.id}/toggle")
    db.expire_all()
    assert db.get(User, member1.id).is_active is False


def test_handover_lets_the_new_member_reach_the_case(db, seeded, client):
    """인계의 실질 — 받은 위원이 실제로 그 케이스를 열 수 있어야 한다."""
    member1, member2 = seeded["member1"], seeded["member2"]
    case_id = db.scalar(select(Case.id).where(Case.member_id == member1.id))

    _login(client, "member2@ium.test")
    assert client.get(f"/member/cases/{case_id}", follow_redirects=False).headers["location"] == "/"

    _login(client, "office@ium.test")
    client.post(
        f"/office/members/{member1.id}/handover", data={"to_member_id": str(member2.id)}
    )

    _login(client, "member2@ium.test")
    assert client.get(f"/member/cases/{case_id}").status_code == 200


def test_handover_is_written_to_the_audit_log(db, seeded, client):
    member1, member2 = seeded["member1"], seeded["member2"]

    _login(client, "office@ium.test")
    client.post(
        f"/office/members/{member1.id}/handover", data={"to_member_id": str(member2.id)}
    )

    logs = list(
        db.scalars(select(IdentityAccessLog).where(IdentityAccessLog.action == "handover")).all()
    )
    assert len(logs) == 3
    assert all("이관희 위원 → 정미영 위원" in log.reason for log in logs)

    # 운영자 화면에도 '담당 변경'으로 보인다 — '수정'으로 뭉뚱그리지 않는다.
    html = client.get("/office").text
    assert "담당 변경" in html


def test_handover_never_exposes_identity_to_the_office(db, seeded, client):
    """배정을 바꿔도 운영자가 내용을 보게 되는 것은 아니다."""
    member1, member2 = seeded["member1"], seeded["member2"]

    _login(client, "office@ium.test")
    html = client.post(
        f"/office/members/{member1.id}/handover",
        data={"to_member_id": str(member2.id)},
        follow_redirects=True,
    ).text

    assert "홍길동" not in html
    assert "010-0000" not in html


def test_handover_to_an_inactive_member_is_refused(db, seeded, client):
    member1, member2 = seeded["member1"], seeded["member2"]
    member2.is_active = False
    db.commit()

    _login(client, "office@ium.test")
    body = client.post(
        f"/office/members/{member1.id}/handover",
        data={"to_member_id": str(member2.id)},
        follow_redirects=True,
    ).text

    assert "위촉이 해제된 상태입니다" in body
    db.expire_all()
    assert _open_case_count(db, member1.id) == 3


def test_handover_to_self_is_refused(db, seeded, client):
    member1 = seeded["member1"]

    _login(client, "office@ium.test")
    body = client.post(
        f"/office/members/{member1.id}/handover",
        data={"to_member_id": str(member1.id)},
        follow_redirects=True,
    ).text

    assert "같은 위원에게는 인계할 수 없습니다" in body


def test_closed_cases_do_not_block_deactivation(db, seeded, client):
    member1 = seeded["member1"]
    for case in db.scalars(select(Case).where(Case.member_id == member1.id)).all():
        case.status = CaseStatus.CLOSED
    db.commit()

    _login(client, "office@ium.test")
    client.post(f"/office/members/{member1.id}/toggle")

    db.expire_all()
    assert db.get(User, member1.id).is_active is False


def test_case_assignment_appears_in_the_permission_matrix(db, seeded, client):
    """위원회에 보여 주는 표에 이 경계가 드러나야 한다."""
    _login(client, "office@ium.test")
    html = client.get("/office").text

    assert "case_assignment" in html
