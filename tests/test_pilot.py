"""파일럿 지표 테스트.

위원회 결정(안건 04): 기간은 1개월이고 시작일은 앱이 완성된 뒤에 정한다. 매칭 건수를 한
숫자로 보지 않고 단계별로 센다. 위원 만족도·활동 위원 수는 지표에서 뺀다.

2차 결정(안건 16): 목표 숫자를 미리 정하지 않고, 전달 완료 건수를 위원들이 함께 보는
성과 자료로 쓴다.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app import matching, pilot, retention
from app.models import Case, CaseStatus, Offer, OfferStatus, Shop
from app.models.policy import DEFAULT_PILOT_MONTHS


def _login(client, email: str) -> None:
    client.post("/login", data={"email": email, "password": "ium1234"}, follow_redirects=False)


def _offer(db, *, when: datetime | None = None, status=OfferStatus.OPEN) -> Offer:
    shop = db.scalar(select(Shop))
    kind = db.scalar(select(Offer)).kind
    offer = Offer(
        council_id=shop.council_id, shop_id=shop.id, title="집계용 나눔",
        kind=kind, status=status,
    )
    db.add(offer)
    db.flush()
    if when is not None:
        offer.created_at = when
    db.commit()
    return offer


# --- 기간 ------------------------------------------------------------------


def test_default_period_is_one_month_with_no_start_date(db):
    """시작일은 회의에서 정하지 않았다 — 비어 있어야 한다."""
    policy = retention.current(db)
    assert policy.pilot_months == DEFAULT_PILOT_MONTHS == 1
    assert policy.pilot_start is None


def test_without_a_start_date_counting_is_cumulative(db):
    win = pilot.window(retention.current(db))
    assert not win.is_set
    assert win.contains(datetime(2020, 1, 1))  # 아무 시점이나 포함된다
    assert win.days_left() is None
    assert "누적" in win.label


def test_window_runs_one_month_from_the_start(db, seeded, client):
    _login(client, "member1@ium.test")
    client.post("/manage/policy/pilot", data={"start": "2026-10-15", "months": "1"})

    db.expire_all()
    win = pilot.window(retention.current(db))
    assert win.start == date(2026, 10, 15)
    assert win.end == date(2026, 11, 15)
    assert win.contains(datetime(2026, 10, 20, 3, 0))
    assert not win.contains(datetime(2026, 11, 20, 3, 0))


def test_window_end_lands_on_a_real_date(db):
    policy = retention.current(db)
    policy.pilot_start = date(2026, 1, 31)
    policy.pilot_months = 1
    win = pilot.window(policy)
    assert win.end == date(2026, 2, 28)


def test_days_left_turns_negative_after_the_end(db):
    policy = retention.current(db)
    policy.pilot_start = date(2026, 10, 1)
    policy.pilot_months = 1
    win = pilot.window(policy)

    assert win.days_left(today=date(2026, 10, 20)) == 12
    assert win.days_left(today=date(2026, 11, 10)) == -9


def test_clearing_the_start_date_returns_to_cumulative(db, seeded, client):
    _login(client, "member1@ium.test")
    client.post("/manage/policy/pilot", data={"start": "2026-10-15", "months": "1"})
    body = client.post(
        "/manage/policy/pilot", data={"start": "", "months": "1"}, follow_redirects=True
    ).text

    assert "누적" in body
    db.expire_all()
    assert retention.current(db).pilot_start is None


@pytest.mark.parametrize(
    "data,expect",
    [
        ({"start": "어제", "months": "1"}, "시작일은"),
        ({"start": "", "months": "석달"}, "숫자"),
        ({"start": "", "months": "0"}, "사이로"),
        ({"start": "", "months": "99"}, "사이로"),
    ],
)
def test_bad_pilot_input_is_guided(db, seeded, client, data, expect):
    _login(client, "member1@ium.test")
    body = client.post("/manage/policy/pilot", data=data, follow_redirects=True).text
    assert expect in body


def test_only_the_manager_can_set_the_pilot_period(db, seeded, client):
    for email in ("member2@ium.test", "member3@ium.test", "blue@ium.test"):
        _login(client, email)
        res = client.post(
            "/manage/policy/pilot", data={"start": "2026-10-15", "months": "1"},
            follow_redirects=False,
        )
        assert res.headers["location"] == "/", email


# --- 단계별 집계 -------------------------------------------------------------


def test_funnel_separates_every_stage(db, seeded):
    """한 숫자로 뭉치지 않는 것이 이 안건의 요지다."""
    from app import accounts

    waiting, _ = accounts.register_donor(
        db, seeded["member1"], name="대기사장", phone="010-7777-0002"
    )
    _offer(db)

    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.mark_delivered(db, match, seeded["member1"])

    counts = pilot.funnel(db, pilot.window(retention.current(db)), seeded["member1"])

    assert counts["donors_waiting"] == 1  # 방금 등록한 사람
    assert counts["offers_posted"] >= 1
    assert counts["matched"] == 1
    assert counts["delivered"] == 1
    assert counts["cancelled"] == 0
    assert waiting.approved_at is None


def test_cancelled_matches_are_counted_separately(db, seeded):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.cancel(db, match, seeded["member1"], "가정 사정")

    counts = pilot.funnel(db, pilot.window(retention.current(db)), seeded["member1"])
    assert counts["cancelled"] == 1
    assert counts["matched"] == 0  # 취소된 건은 매칭 성과로 세지 않는다


def test_counting_is_limited_to_the_pilot_window(db, seeded):
    """기간을 정하면 그 전에 올라온 나눔글은 빠진다.

    기간을 과거로 고정한다. '이번 달'로 잡으면 시드 데이터가 기간 안에 들어와, 날짜가
    지나면서 테스트가 깨진다 — 실제로 한 번 깨졌다.
    """
    before = _offer(db, when=datetime(2025, 12, 5, 3, 0))   # 기간 전
    inside = _offer(db, when=datetime(2026, 1, 20, 3, 0))   # 기간 안

    policy = retention.current(db)
    policy.pilot_start = date(2026, 1, 15)
    policy.pilot_months = 1
    db.commit()

    counts = pilot.funnel(db, pilot.window(policy), seeded["member1"])
    assert counts["offers_posted"] == 1  # inside 만. 시드 나눔글도 기간 밖이다.
    assert before.id != inside.id


def test_no_targets_are_set_in_advance(db):
    """위원회 결정(안건 16): 목표 숫자를 미리 정하지 않는다.

    숫자를 걸어 두면 숫자를 맞추는 일이 목적이 된다. 전달 완료 건수만 세어 공유한다.
    """
    assert not hasattr(pilot, "GOALS")
    assert not hasattr(pilot, "goals")


def test_delivered_count_is_the_shared_number(db, seeded):
    case = db.scalar(select(Case).where(Case.status == CaseStatus.OPEN))
    offer = db.scalar(select(Offer).where(Offer.status == OfferStatus.OPEN))
    match = matching.propose(db, case, offer, seeded["member1"])
    matching.mark_delivered(db, match, seeded["member1"])

    counts = pilot.funnel(db, pilot.window(retention.current(db)), seeded["member1"])
    assert counts["delivered"] == 1


# --- 화면 ------------------------------------------------------------------


def test_dashboard_shows_every_stage(db, seeded, client):
    _login(client, "member1@ium.test")
    html = client.get("/manage").text

    for label in ("후원자 승인", "승인 대기", "나눔글 접수", "위원 매칭", "매칭 취소", "전달 완료"):
        assert label in html, label


def test_dashboard_shows_no_target_numbers(db, seeded, client):
    _login(client, "member1@ium.test")
    html = client.get("/manage").text
    assert "파일럿 목표 대비" not in html
    assert "목표 숫자는 미리 정하지 않습니다" in html


def test_dashboard_shows_the_period_and_days_left(db, seeded, client):
    _login(client, "member1@ium.test")
    assert "기간 미설정" in client.get("/manage").text

    client.post("/manage/policy/pilot", data={"start": "2026-10-15", "months": "1"})
    html = client.get("/manage").text
    assert "2026-10-15" in html and "2026-11-15" in html
