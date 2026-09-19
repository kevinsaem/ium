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


# --- 나눔글 노출 심사 (안건 05) ---------------------------------------------


def _post_offer(client, db) -> int:
    """후원자가 새 나눔글을 올린다 — 승인 대기 상태로 들어간다."""
    from sqlalchemy import select as _select

    from app.models import Offer

    client.post("/login", data={"email": "blue@ium.test", "password": "ium1234"})
    client.post(
        "/donor/offers",
        data={"title": "라면 20박스", "kind": "goods", "delivery": "member_pickup"},
    )
    return db.scalar(_select(Offer.id).where(Offer.title == "라면 20박스"))


def test_new_offer_waits_and_is_hidden_from_members(db, seeded, client):
    from app.models import Offer, OfferStatus

    offer_id = _post_offer(client, db)
    assert db.get(Offer, offer_id).status is OfferStatus.PENDING

    # 위원의 매칭 후보에 오르지 않는다
    _login(client, "member1@ium.test")
    case_id = db.scalar(select(Case.id).where(Case.member_id == seeded["member1"].id))
    assert "라면 20박스" not in client.get(f"/member/cases/{case_id}").text

    # 운영자 현황판에는 승인 대기로 뜬다
    _login(client, "office@ium.test")
    assert "라면 20박스" in client.get("/office").text


def test_office_approves_and_members_can_then_match(db, seeded, client):
    from app.models import Offer, OfferStatus

    offer_id = _post_offer(client, db)

    _login(client, "office@ium.test")
    client.post(f"/office/offers/{offer_id}/approve", data={"note": "현장 확인"})

    db.expire_all()
    assert db.get(Offer, offer_id).status is OfferStatus.OPEN

    _login(client, "member1@ium.test")
    case_id = db.scalar(select(Case.id).where(Case.member_id == seeded["member1"].id))
    assert "라면 20박스" in client.get(f"/member/cases/{case_id}").text


def test_rejection_reason_reaches_the_donor(db, seeded, client):
    from app.models import Offer, OfferStatus

    offer_id = _post_offer(client, db)

    _login(client, "office@ium.test")
    client.post(f"/office/offers/{offer_id}/reject", data={"note": "유통기한이 지났습니다"})

    db.expire_all()
    assert db.get(Offer, offer_id).status is OfferStatus.REJECTED

    _login(client, "blue@ium.test")
    body = client.get("/donor/mine").text
    assert "유통기한이 지났습니다" in body
    assert "다시 접수" in body


def test_rejection_without_a_reason_is_refused(db, seeded, client):
    from app.models import Offer, OfferStatus

    offer_id = _post_offer(client, db)

    _login(client, "office@ium.test")
    body = client.post(
        f"/office/offers/{offer_id}/reject", data={"note": "  "}, follow_redirects=True
    ).text

    assert "거절 사유를 입력해 주세요" in body
    db.expire_all()
    assert db.get(Offer, offer_id).status is OfferStatus.PENDING


def test_rejected_offer_goes_back_for_review_not_straight_out(db, seeded, client):
    """고쳐서 다시 올린 글은 심사를 다시 받는다 — 거절을 우회하는 길이 되면 안 된다."""
    from app.models import Offer, OfferStatus

    offer_id = _post_offer(client, db)
    _login(client, "office@ium.test")
    client.post(f"/office/offers/{offer_id}/reject", data={"note": "사유"})

    _login(client, "blue@ium.test")
    client.post(f"/donor/offers/{offer_id}/reopen")

    db.expire_all()
    offer = db.get(Offer, offer_id)
    assert offer.status is OfferStatus.PENDING
    assert offer.review_note is None


def test_only_office_can_review_offers(db, seeded, client):
    from app.models import Offer, OfferStatus

    offer_id = _post_offer(client, db)

    for email in ("member1@ium.test", "blue@ium.test"):
        _login(client, email)
        res = client.post(f"/office/offers/{offer_id}/approve", follow_redirects=False)
        assert res.headers["location"] == "/", email

    db.expire_all()
    assert db.get(Offer, offer_id).status is OfferStatus.PENDING


def test_pending_offer_is_hidden_from_the_donor_feed(db, seeded, client):
    """심사 전 글은 후원자 피드에도 오르지 않는다. 동네에 공개된 나눔은 확인을 거친 것뿐이다."""
    _post_offer(client, db)

    _login(client, "blue@ium.test")
    assert "라면 20박스" not in client.get("/donor").text
    # 다만 본인의 '내 나눔글'에서는 진행 상황이 보인다
    assert "라면 20박스" in client.get("/donor/mine").text
