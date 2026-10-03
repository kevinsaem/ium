"""식별정보 보관 기한 테스트.

위원회 결정(2026-09-19, 안건 01): 케이스 종결 후 3개월까지 보관하고 파기한다. 기간은
하드코딩하지 않고 운영자가 화면에서 바꾼다.

이 파일이 지키는 것은 두 가지다 — 기한이 제대로 계산되는가, 그리고 운영자가 기한을
집행하면서도 내용을 보지는 못하는가.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app import identity_service, retention
from app.models import Case, CaseIdentity, CaseStatus, IdentityAccessLog, Policy
from app.models.policy import DEFAULT_RETENTION_MONTHS

ROOT = Path(__file__).resolve().parent.parent


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _close(db, case, when: datetime) -> Case:
    case.status = CaseStatus.CLOSED
    case.closed_at = when
    db.commit()
    return case


# --- 기본값과 변경 -----------------------------------------------------------


def test_default_is_three_months(db):
    """회의에서 정한 기본값. 코드가 아니라 DB 에 있고 화면에서 바뀐다."""
    assert retention.current(db).identity_retention_months == DEFAULT_RETENTION_MONTHS == 3


def test_policy_row_is_created_once(db):
    first = retention.current(db)
    second = retention.current(db)
    assert first.id == second.id == 1
    assert len(list(db.scalars(select(Policy)).all())) == 1


def test_office_can_change_the_period_from_the_screen(db, seeded, client):
    _login(client, "office@ium.test")
    body = client.post(
        "/office/policy/retention", data={"months": "6"}, follow_redirects=True
    ).text

    assert "종결 후 6개월" in body
    db.expire_all()
    policy = retention.current(db)
    assert policy.identity_retention_months == 6
    assert policy.updated_by_id == seeded["office"].id  # 누가 바꿨는지 남는다


@pytest.mark.parametrize("bad,expect", [("", "숫자"), ("석달", "숫자"), ("0", "사이로"), ("61", "사이로")])
def test_bad_period_is_guided_and_keeps_the_old_value(db, seeded, client, bad, expect):
    _login(client, "office@ium.test")
    body = client.post(
        "/office/policy/retention", data={"months": bad}, follow_redirects=True
    ).text

    assert expect in body
    db.expire_all()
    assert retention.current(db).identity_retention_months == 3


def test_only_office_can_change_the_period(db, seeded, client):
    for email in ("member1@ium.test", "blue@ium.test"):
        _login(client, email)
        res = client.post(
            "/office/policy/retention", data={"months": "12"}, follow_redirects=False
        )
        assert res.headers["location"] == "/", email

    db.expire_all()
    assert retention.current(db).identity_retention_months == 3


# --- 기한 계산 ---------------------------------------------------------------


def test_an_open_case_has_no_deadline(db, seeded):
    """기한은 종결한 날부터 센다. 진행 중인 케이스에는 기한이 없다."""
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    assert retention.deadline(case, 3) is None


def test_deadline_is_three_months_after_closing(db, seeded):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))
    assert retention.deadline(case, 3) == date(2026, 4, 15)


def test_deadline_crosses_the_year(db, seeded):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 11, 20, 3, 0))
    assert retention.deadline(case, 3) == date(2027, 2, 20)


def test_deadline_lands_on_a_real_date_for_short_months(db, seeded):
    """1월 31일 종결 + 1개월은 2월 31일이 될 수 없다. 그 달의 마지막 날로 맞춘다."""
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 31, 3, 0))
    assert retention.deadline(case, 1) == date(2026, 2, 28)


def test_deadline_uses_korean_time(db, seeded):
    """UTC 로 1월 31일 16:00 은 한국 시간 2월 1일이다. 종결일이 하루 밀리면 기한도 밀린다."""
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 31, 16, 0))
    assert retention.deadline(case, 1) == date(2026, 3, 1)


def test_reopening_a_case_stops_the_clock(db, seeded, client):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))

    _login(client, "member1@ium.test")
    client.post(f"/member/cases/{case.id}/close")
    db.expire_all()
    assert db.get(Case, case.id).closed_at is not None

    client.post(f"/member/cases/{case.id}/reopen")
    db.expire_all()
    assert db.get(Case, case.id).closed_at is None
    assert retention.deadline(db.get(Case, case.id), 3) is None


def test_status_label_counts_down_then_reports_overdue(db, seeded):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    before = retention.status_for(case, 3, today=date(2026, 4, 10))
    assert before.days_left == 5 and not before.is_overdue
    assert "5일" in before.label

    after = retention.status_for(case, 3, today=date(2026, 4, 20))
    assert after.days_left == -5 and after.is_overdue
    assert "초과" in after.label


def test_a_purged_case_is_no_longer_counted(db, seeded):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))
    identity_service.purge_identity(db, case, seeded["member1"], "종결")

    status = retention.status_for(case, 3, today=date(2026, 12, 1))
    assert not status.holds_identity and not status.is_overdue
    assert status.label == "파기 완료"


def test_expired_lists_only_overdue_cases_still_holding_identity(db, seeded):
    cases = list(db.scalars(select(Case)).all())
    _close(db, cases[0], datetime(2026, 1, 15, 3, 0))       # 기한 지남
    _close(db, cases[1], datetime.now(timezone.utc))         # 방금 종결
    identity_service.purge_identity(db, cases[2], seeded["member1"], "이미 파기")

    overdue = retention.expired(db, 3, today=date(2026, 6, 1))
    assert [c.id for c in overdue] == [cases[0].id]


def test_a_longer_period_postpones_the_deadline(db, seeded):
    """운영자가 기간을 늘리면 기한도 함께 밀린다 — 기한이 코드에 박혀 있지 않다는 확인."""
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    assert retention.expired(db, 3, today=date(2026, 5, 1)) != []
    assert retention.expired(db, 12, today=date(2026, 5, 1)) == []


# --- 화면 표시 ---------------------------------------------------------------


def test_office_sees_the_deadline_but_not_the_contents(db, seeded, client):
    case = db.scalar(select(Case).where(Case.code == "선부3동 A가정"))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    _login(client, "office@ium.test")
    html = client.get("/office/report").text

    assert "선부3동 A가정" in html
    assert "파기 기한" in html
    assert "홍길동" not in html and "010-0000" not in html


def test_overdue_warning_appears_on_the_dashboard(db, seeded, client):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    _login(client, "office@ium.test")
    assert "파기 기한 초과" in client.get("/office").text


def test_no_warning_when_nothing_is_overdue(db, seeded, client):
    _login(client, "office@ium.test")
    assert "파기 기한 초과" not in client.get("/office").text


def test_member_sees_the_deadline_on_the_case(db, seeded, client):
    case = db.scalar(select(Case).where(Case.member_id == seeded["member1"].id))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    _login(client, "member1@ium.test")
    body = client.get(f"/member/cases/{case.id}").text
    assert "파기 기한" in body and "2026-04-15" in body


# --- 운영자의 기한 집행 권한 -------------------------------------------------


def test_office_can_destroy_without_being_able_to_read(db, seeded):
    """'운영자는 식별정보를 볼 수 없다'와 '보관 기한을 집행한다'가 함께 성립해야 한다."""
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    # 읽기는 여전히 막힌다
    with pytest.raises(Exception) as exc:
        identity_service.read_identity(db, case, seeded["office"], "궁금해서")
    assert "위원만" in str(exc.value)

    # 파기는 할 수 있다
    identity_service.purge_expired_identity(db, case, seeded["office"], "보관 기간 경과")
    db.expire_all()
    assert db.get(Case, case.id).identity is None


def test_members_cannot_use_the_retention_purge_path(db, seeded):
    """위원은 담당 케이스만 파기한다. 기한 집행 경로로 남의 케이스를 지울 수는 없다."""
    case = db.scalar(select(Case))
    with pytest.raises(Exception) as exc:
        identity_service.purge_expired_identity(db, case, seeded["member1"], "기한")
    assert "운영자만" in str(exc.value)


def test_purge_is_logged_as_purge_not_as_an_edit(db, seeded):
    case = db.scalar(select(Case))
    identity_service.purge_identity(db, case, seeded["member1"], "종결 후 파기")

    log = db.scalar(
        select(IdentityAccessLog)
        .where(IdentityAccessLog.case_id == case.id)
        .order_by(IdentityAccessLog.id.desc())
    )
    assert log.action == "purge"
    assert "종결 후 파기" in log.reason


def test_purge_leaves_the_case_and_its_statistics(db, seeded):
    """파기는 식별정보만 지운다. 비식별 기록과 통계는 그대로여야 보고서가 유지된다."""
    case = db.scalar(select(Case))
    code, need = case.code, case.need_summary

    identity_service.purge_identity(db, case, seeded["member1"], "종결")

    db.expire_all()
    kept = db.get(Case, case.id)
    assert kept is not None and kept.code == code and kept.need_summary == need
    assert db.scalar(select(CaseIdentity).where(CaseIdentity.case_id == case.id)) is None


def test_permission_matrix_shows_the_retention_boundary(db, seeded, client):
    _login(client, "office@ium.test")
    assert "identity_retention" in client.get("/office").text


# --- 일괄 파기 명령 -----------------------------------------------------------


def test_purge_command_shows_targets_before_touching_anything(db, seeded, client, tmp_path):
    """기본이 '보여 주기'인 이유: 파기는 되돌릴 수 없다."""
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))
    code = case.code

    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(ROOT),
        "IUM_DATABASE_URL": os.environ["IUM_DATABASE_URL"],
    }
    listed = subprocess.run(
        [sys.executable, "-m", "app.purge_expired"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )

    assert listed.returncode == 0, listed.stderr
    assert code in listed.stdout
    assert "--apply" in listed.stdout
    db.expire_all()
    assert db.get(Case, case.id).identity is not None  # 아직 지워지지 않았다


def test_purge_command_needs_an_actor_for_the_record(db, seeded, tmp_path):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "app.purge_expired", "--apply"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )

    assert result.returncode != 0
    assert "--actor" in result.stderr
    db.expire_all()
    assert db.get(Case, case.id).identity is not None


def test_purge_command_destroys_and_records_who_ran_it(db, seeded):
    """--apply 는 실제로 지운다. 행위자가 기록에 남아야 나중에 설명할 수 있다."""
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))
    case_id = case.id

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "app.purge_expired", "--apply", "--actor", "office@ium.test"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "파기했습니다" in result.stdout

    db.expire_all()
    assert db.get(Case, case_id).identity is None
    assert db.get(Case, case_id) is not None  # 비식별 케이스는 남는다

    log = db.scalar(
        select(IdentityAccessLog)
        .where(IdentityAccessLog.case_id == case_id, IdentityAccessLog.action == "purge")
    )
    assert log.actor_id == seeded["office"].id
    assert "보관 기간" in log.reason


def test_purge_command_refuses_a_member_as_actor(db, seeded):
    case = db.scalar(select(Case))
    _close(db, case, datetime(2026, 1, 15, 3, 0))

    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, "-m", "app.purge_expired", "--apply", "--actor", "member1@ium.test"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )

    assert result.returncode != 0
    assert "운영자 계정을 찾을 수 없습니다" in result.stderr
    db.expire_all()
    assert db.get(Case, case.id).identity is not None
