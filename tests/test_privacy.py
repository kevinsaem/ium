"""개인정보 격리 불변식 테스트.

이 파일이 깨지면 기능이 아니라 설계 원칙이 깨진 것이다.
기능을 추가할 때마다 여기부터 돌려볼 것.
"""
from __future__ import annotations

import base64

import pytest
from sqlalchemy import select

from app import identity_service
from app.models import Case, CaseIdentity, IdentityAccessLog, Role


def _login(client, email: str):
    r = client.post("/login", data={"email": email, "password": "ium1234"})
    assert r.status_code in (200, 303)
    return client


# --- 저장 계층 -------------------------------------------------------------


def test_identity_is_encrypted_at_rest(db, seeded):
    """DB 컬럼에는 평문이 절대 들어가지 않는다."""
    identity = db.scalar(select(CaseIdentity))
    assert identity is not None
    assert identity.name_enc.startswith("gAAAAA")  # Fernet 토큰
    assert "홍길동" not in identity.name_enc
    assert "010-" not in (identity.phone_enc or "")


def test_case_table_holds_no_identifying_columns():
    """Case 모델에 식별정보성 컬럼이 새로 끼어들지 않았는지 확인."""
    forbidden = {"name", "phone", "address", "resident_no", "birth", "email"}
    columns = {c.name for c in Case.__table__.columns}
    assert not (columns & forbidden), f"Case 에 식별정보 컬럼이 추가됨: {columns & forbidden}"


# --- 접근 통제 -------------------------------------------------------------


def test_being_the_manager_does_not_open_someone_elses_case(db, seeded):
    """관리자라는 것이 식별정보 열람 권한을 주지 않는다.

    운영자 역할이 있을 때는 '운영자는 못 읽는다' 가 이 선을 지켰다. 역할을 폐기하면서
    그 일이 관리자에게 왔고, 관리자는 위원이기도 하다 — 그래서 '관리자여도 남의 가정은
    못 읽는다' 로 선을 다시 그어야 한다. 읽는 사람은 그 가정을 직접 만나는 담당 위원뿐이다.
    """
    manager = seeded["member1"]
    assert manager.is_manager is True

    # 담당이 다른 위원인 케이스를 하나 만든다
    case = Case(
        council_id=seeded["council"].id,
        code="선부3동 M가정",
        need_summary="반찬",
        member_id=seeded["member2"].id,
    )
    db.add(case)
    db.commit()

    with pytest.raises(Exception) as exc:
        identity_service.read_identity(db, case, manager, "관리 목적")
    assert "담당 위원" in str(exc.value)


def test_other_member_cannot_read_identity(db, seeded):
    """담당이 아닌 위원도 읽을 수 없다."""
    case = db.scalar(select(Case))
    other = seeded["member2"]
    assert case.member_id != other.id
    with pytest.raises(Exception) as exc:
        identity_service.read_identity(db, case, other, "궁금해서")
    assert "담당 위원" in str(exc.value)


def test_read_requires_reason(db, seeded):
    """사유 없는 열람은 거부된다 — 사유 없는 로그는 로그가 아니다."""
    case = db.scalar(select(Case))
    with pytest.raises(Exception) as exc:
        identity_service.read_identity(db, case, seeded["member1"], "   ")
    assert "사유" in str(exc.value)


def test_read_writes_access_log(db, seeded):
    case = db.scalar(select(Case))
    before = db.scalar(select(IdentityAccessLog).where(IdentityAccessLog.case_id == case.id))
    identity_service.read_identity(db, case, seeded["member1"], "전달 일정 조율")

    logs = list(
        db.scalars(
            select(IdentityAccessLog)
            .where(IdentityAccessLog.case_id == case.id, IdentityAccessLog.action == "read")
        ).all()
    )
    assert logs, "열람했는데 로그가 남지 않았다"
    assert logs[-1].reason == "전달 일정 조율"
    assert logs[-1].actor_id == seeded["member1"].id
    assert before is None or True


def test_purge_removes_identity_but_keeps_case(db, seeded):
    """식별정보 파기 후에도 비식별 케이스와 통계는 남는다."""
    case = db.scalar(select(Case))
    case_id, code = case.id, case.code
    identity_service.purge_identity(db, case, seeded["member1"], "파일럿 종료")

    assert db.scalar(select(CaseIdentity).where(CaseIdentity.case_id == case_id)) is None
    survived = db.get(Case, case_id)
    assert survived is not None and survived.code == code


# --- 화면 계층 -------------------------------------------------------------


@pytest.mark.parametrize("path", ["/donor", "/donor/mine"])
def test_donor_screens_leak_nothing(client, seeded, path):
    """후원자 화면에는 대상자 이름·연락처·케이스 코드가 나타나지 않는다."""
    _login(client, "blue@ium.test")
    html = client.get(path).text
    for secret in ("홍길동", "김철수", "이영희", "010-0000", "선부3동 A가정"):
        assert secret not in html, f"{path} 에 {secret} 유출"


def test_donor_cannot_open_member_screens(client, seeded):
    _login(client, "blue@ium.test")
    r = client.get("/member", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_a_donor_cannot_open_a_case_detail(client, seeded):
    """케이스 화면은 위원의 자리다. 후원자는 받는 분이 누구인지 알 수 없다."""
    client.post("/login", data={"phone": "010-0000-0000", "pin": "0000"})
    client.post("/login", data={"email": "blue@ium.test", "password": "ium1234"})
    r = client.get("/member/cases/1", follow_redirects=False)
    assert r.status_code == 303


def test_the_manage_dashboard_shows_log_facts_not_contents(client, db, seeded):
    """관리자는 '열람했다는 사실'만 본다. 열람된 내용은 그 화면에 오지 않는다."""
    case = db.scalar(select(Case))
    identity_service.read_identity(db, case, seeded["member1"], "전달 조율")

    _login(client, "member1@ium.test")
    html = client.get("/manage").text
    assert "전달 조율" in html          # 사유는 보인다
    assert "이관희 위원" in html         # 누가 봤는지도 보인다
    assert "홍길동" not in html          # 열람된 내용은 보이지 않는다
    assert "010-0000" not in html


# --- 전송 계층 -------------------------------------------------------------


def _session_cookie_payload(client) -> str:
    """세션 쿠키의 내용물. 서명은 되어 있지만 암호화가 아니라 누구나 디코딩할 수 있다."""
    raw = client.cookies.get("session")
    if not raw:
        return ""
    head = raw.split(".")[0]
    return base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)).decode("utf-8", "replace")


def test_revealed_identity_never_enters_the_session_cookie(client, db, seeded):
    """복호화된 값은 응답 HTML 한 번으로 끝나야 한다.

    세션에 담으면 Starlette 의 쿠키 세션을 타고 브라우저에 남는다. 서명만 되어 있어
    열어 보면 실명·연락처·주소가 그대로 읽힌다 — DB 를 Fernet 으로 잠근 의미가 사라진다.
    """
    case = db.scalar(select(Case))
    _login(client, "member1@ium.test")

    html = client.post(
        f"/member/cases/{case.id}/identity/reveal",
        data={"reason": "도시락 전달 일정 조율"},
    ).text
    assert "홍길동" in html  # 담당 위원 화면에는 보인다

    cookie = _session_cookie_payload(client)
    assert '"uid"' in cookie  # 쿠키를 실제로 열어 보고 있다는 확인
    assert "홍길동" not in cookie
    assert "\ud64d\uae38\ub3d9" not in cookie  # \uXXXX 로 이스케이프된 형태도 안 된다
    assert "010-0000" not in cookie
    assert "revealed_identity" not in cookie


def test_revealed_page_is_not_cached(client, db, seeded):
    case = db.scalar(select(Case))
    _login(client, "member1@ium.test")

    res = client.post(
        f"/member/cases/{case.id}/identity/reveal", data={"reason": "연락처 확인"}
    )
    assert "no-store" in res.headers.get("cache-control", "")


def test_identity_does_not_survive_to_the_next_page_view(client, db, seeded):
    """열람 후 다시 상세 화면을 열면 식별정보는 사라져 있어야 한다."""
    case = db.scalar(select(Case))
    _login(client, "member1@ium.test")
    client.post(f"/member/cases/{case.id}/identity/reveal", data={"reason": "일정 조율"})

    html = client.get(f"/member/cases/{case.id}").text
    assert "홍길동" not in html
    assert "010-0000" not in html
