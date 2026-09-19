"""운영자 기록 화면 테스트 — 월간 보고서, 감사 기록, 시간 기준.

보고서는 시청에 제출되는 문서이고 감사 기록은 민원·감사 때 유일한 설명 수단이다.
둘 다 '숫자가 맞는가'와 '내용이 새지 않는가'를 함께 고정한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import identity_service, matching
from app.models import (
    Case,
    CaseStatus,
    IdentityAccessLog,
    Offer,
    OfferStatus,
)
from app.timeutil import current_month, in_month, month_bounds, month_label, parse_month, shift_month


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _deliver_one(db, seeded):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.mark_delivered(db, match, seeded["member1"])
    return match


def _last_month() -> tuple[int, int]:
    return shift_month(*current_month(), -1)


# --- 시간 기준 -------------------------------------------------------------


def test_month_is_bucketed_in_korean_time():
    # UTC 8월 31일 23:30 은 한국 시간 9월 1일 08:30 이다. SQLite 가 돌려주는 모양(tzinfo 없음) 그대로.
    stored = datetime(2026, 8, 31, 23, 30)
    assert in_month(stored, 2026, 9)
    assert not in_month(stored, 2026, 8)


def test_month_bounds_are_korean_midnights():
    start, end = month_bounds(2026, 12)
    assert start == datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 12, 31, 15, 0, tzinfo=timezone.utc)


def test_parse_month_falls_back_instead_of_failing():
    assert parse_month("2026-08") == (2026, 8)
    for bad in ("", "abc", "2026-13", "2026-08-01", None):
        assert parse_month(bad) == current_month()


def test_shift_month_crosses_years():
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2025, 12, 1) == (2026, 1)


# --- 월간 보고서 -----------------------------------------------------------


def test_office_report_counts_the_whole_dong(db, seeded, client):
    db.add(Case(code="선부3동 D가정", need_summary="반찬", member_id=seeded["member2"].id))
    db.commit()

    _login(client, "office@ium.test")
    html = client.get("/office/report").text

    assert "당월 발굴 케이스 4건" in html  # 두 위원의 케이스를 모두 센다
    assert "당월 활동 위원 2명" in html


def test_report_counts_only_the_reporting_month(db, seeded, client):
    y, m = _last_month()
    case = db.scalar(select(Case).where(Case.code == "선부3동 C어르신"))
    case.created_at = datetime(y, m, 15, 3, 0)
    db.commit()

    _login(client, "office@ium.test")
    assert "당월 발굴 케이스 2건" in client.get("/office/report").text
    assert "당월 발굴 케이스 1건" in client.get(f"/office/report?month={y:04d}-{m:02d}").text


def test_member_report_uses_the_same_month_rule(db, seeded, client):
    """위원 보고서도 같은 기준이다. 예전에는 '9월 보고서'에 누적 케이스 수가 찍혔다."""
    y, m = _last_month()
    case = db.scalar(select(Case).where(Case.code == "선부3동 C어르신"))
    case.created_at = datetime(y, m, 15, 3, 0)
    db.commit()

    _login(client, "member1@ium.test")
    assert "당월 발굴 케이스 2건" in client.get("/member/report").text


def test_delivery_just_after_korean_midnight_lands_in_the_new_month(db, seeded, client, member_mode):
    match = _deliver_one(db, seeded)
    start, _ = month_bounds(*current_month())
    # 이번 달 1일 00:30 (한국). UTC 로는 아직 지난달 마지막 날이다.
    match.delivered_at = (start + timedelta(minutes=30)).replace(tzinfo=None)
    db.commit()

    _login(client, "office@ium.test")
    assert "당월 전달 완료 1건" in client.get("/office/report").text


def test_office_report_contains_no_identity(db, seeded, client, member_mode):
    _deliver_one(db, seeded)

    _login(client, "office@ium.test")
    html = client.get("/office/report").text

    assert "홍길동" not in html
    assert "010-0000" not in html
    assert "안산시" not in html


def test_resolved_case_still_holding_identity_is_flagged(db, seeded, client, member_mode):
    """전달은 끝났는데 식별정보가 남아 있으면 운영자에게 '파기 대기'로 보인다 — 내용은 아니고."""
    match = _deliver_one(db, seeded)

    _login(client, "office@ium.test")
    assert "식별정보 파기 대기" in client.get("/office/report").text

    identity_service.purge_identity(db, match.case, seeded["member1"], "전달 완료 후 파기")
    assert "식별정보 파기 대기" not in client.get("/office/report").text


# --- 감사 기록 -------------------------------------------------------------


def _add_logs(db, case, actor, n, reason, action="read", when=None):
    for i in range(n):
        log = IdentityAccessLog(case_id=case.id, actor_id=actor.id, action=action, reason=f"{reason} {i}")
        if when is not None:
            log.accessed_at = when
        db.add(log)
    db.commit()


def test_audit_log_pages_through_everything(db, seeded, client):
    case = db.scalar(select(Case))
    _add_logs(db, case, seeded["member1"], 60, "일정 조율")  # + 시드의 등록 기록 3건

    _login(client, "office@ium.test")
    first = client.get("/office/audit").text
    assert f"{month_label(*current_month())} · 63건" in first
    assert "1 / 2" in first
    assert "2 / 2" in client.get("/office/audit?page=2").text


def test_audit_log_answers_what_happened_last_month(db, seeded, client):
    y, m = _last_month()
    start, _ = month_bounds(y, m)
    case = db.scalar(select(Case))
    _add_logs(db, case, seeded["member2"], 1, "지난달 열람", when=start + timedelta(days=3))

    _login(client, "office@ium.test")
    last = client.get(f"/office/audit?month={y:04d}-{m:02d}").text
    assert "지난달 열람" in last
    assert f"{month_label(y, m)} · 1건" in last

    assert "지난달 열람" not in client.get("/office/audit").text
    assert "지난달 열람" in client.get("/office/audit?month=all").text


def test_audit_log_filters_by_person_and_action(db, seeded, client):
    case = db.scalar(select(Case))
    _add_logs(db, case, seeded["member2"], 2, "정미영 확인")
    label = month_label(*current_month())

    _login(client, "office@ium.test")
    by_person = client.get(f"/office/audit?actor={seeded['member2'].id}&action=read").text
    assert f"{label} · 2건" in by_person

    writes = client.get("/office/audit?action=write").text
    assert f"{label} · 3건" in writes  # 시드의 식별정보 등록 기록


def test_audit_log_shows_case_code_and_reason_but_never_content(db, seeded, client):
    case = db.scalar(select(Case).where(Case.code == "선부3동 A가정"))
    identity_service.read_identity(db, case, seeded["member1"], "도시락 전달 일정 조율")

    _login(client, "office@ium.test")
    html = client.get("/office/audit").text

    assert "선부3동 A가정" in html
    assert "도시락 전달 일정 조율" in html
    assert "홍길동" not in html
    assert "010-0000" not in html


def test_records_survive_garbage_query_params(db, seeded, client):
    _login(client, "office@ium.test")
    for path in (
        "/office/audit?page=abc&actor=x&action=nope&month=zzz",
        "/office/audit?page=999",
        "/office/report?month=2026-99",
    ):
        assert client.get(path).status_code == 200, path


def test_records_are_office_only(db, seeded, client):
    for email in ("member1@ium.test", "blue@ium.test"):
        _login(client, email)
        for path in ("/office/report", "/office/audit"):
            assert client.get(path, follow_redirects=False).headers["location"] == "/", (email, path)


def test_dashboard_links_to_the_full_audit_log(db, seeded, client):
    _login(client, "office@ium.test")
    assert 'href="/office/audit"' in client.get("/office").text
