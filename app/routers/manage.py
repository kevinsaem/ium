"""관리자 화면 — 협의체를 운영하는 한 사람의 자리.

관리자(OFFICE) 역할이 하던 일이 여기로 왔다. 관리자 = 매니저 = 협의체당 한 사람
(2026-10-24 결정)이므로, 위원을 들이는 사람과 후원자를 승인하는 사람과 협의체 현황을
보는 사람이 같다. 역할을 하나 줄이면 사전 승인에서 설명할 것도 하나 줄어든다.

역할이 줄면서 분리 하나가 사라졌다. 관리자는 식별정보를 못 읽으면서 보관 기한이 지난
것을 파기할 수 있었는데, 그 자리가 없어졌다. 파기 집행은 관리자가 맡는다
(2026-10-24 결정). 관리자도 위원이라 자기 담당 케이스는 읽을 수 있지만, 파기는 내용을
열지 않고 집행되고 누가 언제 했는지 기록에 남는다.

그래서 이 화면에서 지켜야 하는 선은 하나로 줄었다 — 식별정보를 읽는 사람은 그 가정을
직접 만나는 담당 위원뿐이다. 관리자도, 슈퍼 관리자도 아니다.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import (
    accounts,
    identity_service,
    invites,
    matching,
    pilot,
    rendering,
    retention,
    tenancy,
)
from app.config import settings
from app.db import get_db
from app.deps import require_manager
from app.models import (
    AccountEvent,
    Case,
    CaseStatus,
    IdentityAccessLog,
    Match,
    MatchStatus,
    MemberInvite,
    Offer,
    OfferStatus,
    Role,
    Shop,
    User,
)
from app.models.invite import DEFAULT_DAYS, DEFAULT_MAX_USES
from app.permissions import describe
from app.rendering import flash, render
from app.reporting import build_monthly_report
from app.timeutil import (
    KST,
    current_month,
    in_month,
    month_bounds,
    month_label,
    parse_month,
    recent_months,
    shift_month,
    to_local,
)

router = APIRouter(prefix="/manage", dependencies=[Depends(require_manager)])
manager_dep = require_manager

def _member(db: Session, member_id: int, user: User) -> User:
    """주소의 id 로 위원을 찾는다 — 경계 확인까지 여기서 끝낸다.

    라우트마다 확인을 붙이는 방식은 한 번 빠뜨리면 조용히 넘어간다
    (app/routers/member.py 의 _donor 에 적어 둔 사고가 그랬다).
    """
    member = db.get(User, member_id)
    if member is None or member.role is not Role.MEMBER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="위원을 찾을 수 없습니다.")
    tenancy.assert_same(user, member)
    return member


def _donor(db: Session, donor_id: int, user: User) -> User:
    donor = db.get(User, donor_id)
    if donor is None or donor.role is not Role.DONOR:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="후원자를 찾을 수 없습니다.")
    tenancy.assert_same(user, donor)
    return donor


def _account(db: Session, user_id: int, user: User) -> User:
    """잠금 해제·승인처럼 역할을 가리지 않는 동작의 대상 계정."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="계정을 찾을 수 없습니다.")
    tenancy.assert_same(user, target)
    return target


def _shop(db: Session, shop_id: int, user: User) -> Shop:
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="가게를 찾을 수 없습니다.")
    tenancy.assert_same(user, shop)
    return shop


@router.get("")
def dashboard(request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)):
    policy = retention.current(db, user.council_id)
    matches = list(db.scalars(tenancy.scoped(select(Match), Match, user)).all())
    year, month = current_month()
    month_delivered = sum(
        1 for m in matches if m.status is MatchStatus.DELIVERED and in_month(m.delivered_at, year, month)
    )

    stats = {
        "certified_shops": db.scalar(
            tenancy.scoped(select(func.count()).select_from(Shop), Shop, user).where(
                Shop.is_certified
            )
        ),
        "active_members": db.scalar(
            tenancy.scoped(select(func.count()).select_from(User), User, user).where(
                User.role == Role.MEMBER, User.is_active
            )
        ),
        "total_matches": len(matches),
        "month_delivered": month_delivered,
        "open_cases": db.scalar(
            tenancy.scoped(select(func.count()).select_from(Case), Case, user).where(
                Case.status == CaseStatus.OPEN
            )
        ),
        "urgent_cases": db.scalar(
            tenancy.scoped(select(func.count()).select_from(Case), Case, user).where(
                Case.is_urgent, Case.status != CaseStatus.CLOSED
            )
        ),
    }

    # 위원회 결정(안건 04): 단계별로 센다. 기간이 설정돼 있으면 그 기간만.
    pilot_window = pilot.window(policy)
    funnel = pilot.funnel(db, pilot_window, user)

    # 관리자는 '열람했다는 사실'만 본다. 열람된 내용은 이 화면에 오지 않는다.
    audit_logs = list(
        db.scalars(
            tenancy.scoped(select(IdentityAccessLog), IdentityAccessLog, user)
            .options(selectinload(IdentityAccessLog.actor), selectinload(IdentityAccessLog.case))
            .order_by(IdentityAccessLog.accessed_at.desc(), IdentityAccessLog.id.desc())
            .limit(5)
        ).all()
    )

    # 기한이 지났는데 식별정보가 남은 케이스. 관리자는 건수만 본다 — 파기는 담당 위원 몫이다.
    overdue = retention.expired(db, policy.identity_retention_months, viewer=user)

    return render(
        request,
        "manage/dash.html",
        user,
        "dash",
        policy=policy,
        overdue=overdue,
        pilot_window=pilot_window,
        pilot_days_left=pilot_window.days_left(),
        funnel=funnel,
        stats=stats,
        audit_logs=audit_logs,
        permission_rows=describe(),
    )


AUDIT_PAGE_SIZE = 50
AUDIT_ACTION_LABELS = {
    "read": "열람",
    "write": "수정",
    "purge": "파기",
    "handover": "담당 변경",
}


@router.post("/policy/retention")
def update_retention(
    request: Request,
    months: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """식별정보 보관 기간 변경 (위원회 결정, 안건 01).

    "하드코딩으로 하지 말고 관리자 설정에서 정할 수 있도록 한다" — 그래서 .env 가 아니라
    DB 에 두고 이 화면에서 바꾼다. 행정복지센터 협의 결과에 따라 달라질 수 있기 때문이다.
    """
    try:
        policy = retention.update_retention(db, user, months)
    except retention.PolicyError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(
        request,
        f"식별정보 보관 기간을 종결 후 {policy.identity_retention_months}개월로 정했습니다.",
    )
    return RedirectResponse("/manage", status_code=303)


@router.post("/policy/pilot")
def update_pilot(
    request: Request,
    start: str = Form(""),
    months: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """파일럿 기간 설정 (위원회 결정, 안건 04).

    시작일은 "완성되고 나서 해야 되는 거니까" 회의에서 정하지 않았다. 관리자가 앱을 열 날을
    여기에 넣으면 그때부터 지표를 센다.
    """
    try:
        policy = pilot_settings_update(db, user, start, months)
    except retention.PolicyError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    if policy.pilot_start is None:
        flash(request, "파일럿 시작일을 비웠습니다. 지표를 누적으로 셉니다.")
    else:
        flash(
            request,
            f"파일럿 기간을 {policy.pilot_start} 부터 {policy.pilot_months}개월로 정했습니다.",
        )
    return RedirectResponse("/manage", status_code=303)


def pilot_settings_update(db: Session, actor: User, raw_start: str, raw_months: str):
    """시작일과 기간을 함께 저장한다. 잘못된 값은 읽을 수 있는 문장으로 돌려준다."""
    from datetime import date as _date

    policy = retention.current(db)

    text = (raw_months or "").strip()
    if text:
        try:
            months = int(text)
        except ValueError:
            raise retention.PolicyError("파일럿 기간은 숫자(개월)로 입력해 주세요.") from None
        if not 1 <= months <= 24:
            raise retention.PolicyError("파일럿 기간은 1개월에서 24개월 사이로 정해 주세요.")
        policy.pilot_months = months

    start_text = (raw_start or "").strip()
    if not start_text:
        policy.pilot_start = None
    else:
        try:
            policy.pilot_start = _date.fromisoformat(start_text)
        except ValueError:
            raise retention.PolicyError(
                "시작일은 2026-10-15 처럼 입력해 주세요."
            ) from None

    policy.updated_by_id = actor.id
    db.commit()
    db.refresh(policy)
    return policy


@router.get("/report")
def report(
    request: Request, month: str = "", user: User = Depends(manager_dep), db: Session = Depends(get_db)
):
    """동 전체 월간 보고서와 미종결 케이스 현황.

    위원 개인 보고서와 같은 계산(app/reporting.py)을 동 전체에 적용한다. 관리자가 보는 것은
    비식별 코드와 진행 상태뿐이고, 식별정보는 '보관 중인지'만 드러난다.
    """
    year, mon = parse_month(month)
    cases = list(
        db.scalars(
            tenancy.scoped(select(Case), Case, user).options(
                selectinload(Case.member), selectinload(Case.identity)
            )
        ).all()
    )
    matches = list(
        db.scalars(
            tenancy.scoped(select(Match), Match, user).options(
                selectinload(Match.case).selectinload(Case.member),
                selectinload(Match.offer).selectinload(Offer.shop),
            )
        ).all()
    )
    monthly = build_monthly_report(
        cases,
        matches,
        year,
        mon,
        [f"작성: {rendering.dong_of(user)} 지역사회보장협의체"],
        by_member=True,
    )

    # 긴급 먼저, 그다음 오래 묵은 순. 전달은 끝났는데 식별정보가 남은 케이스는 파기 대기다.
    today = datetime.now(KST).date()
    open_rows = [
        {"case": c, "days": (today - to_local(c.created_at).date()).days}
        for c in sorted(
            (c for c in cases if c.status is not CaseStatus.CLOSED),
            key=lambda c: (not c.is_urgent, to_local(c.created_at)),
        )
    ]

    # 종결됐지만 식별정보가 남은 케이스 — 기한이 다가오는 순서로
    policy = retention.current(db)
    retention_rows = sorted(
        (
            retention.status_for(c, policy.identity_retention_months, today)
            for c in cases
            if c.status is CaseStatus.CLOSED and c.has_identity
        ),
        key=lambda r: (r.days_left if r.days_left is not None else 9999),
    )

    prev_y, prev_m = shift_month(year, mon, -1)
    next_y, next_m = shift_month(year, mon, 1)
    has_next = (next_y, next_m) <= current_month()
    return render(
        request,
        "manage/report.html",
        user,
        "records",
        report=monthly,
        open_rows=open_rows,
        retention_rows=retention_rows,
        retention_months=policy.identity_retention_months,
        prev_month=f"{prev_y:04d}-{prev_m:02d}",
        prev_label=month_label(prev_y, prev_m),
        next_month=f"{next_y:04d}-{next_m:02d}" if has_next else None,
        next_label=month_label(next_y, next_m),
    )


@router.get("/audit")
def audit_log(
    request: Request,
    month: str = "",
    actor: str = "",
    action: str = "",
    page: str = "1",
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """식별정보 접근 감사 기록 전체.

    대시보드의 최근 몇 건으로는 '지난달 누가 무엇을 열었나'에 답할 수 없다. 관리자의
    audit_log 읽기 권한이 쓸모 있으려면 기간·사람·행위로 좁혀 끝까지 넘겨 볼 수 있어야 한다.
    내용은 여기에도 오지 않는다 — 사실과 사유만.

    쿼리 값은 전부 문자열로 받아 직접 해석한다. int 로 선언하면 잘못된 값에 JSON 422 가 뜬다.
    """
    conditions = []
    if month == "all":
        month_value = "all"
        period_text = "전체 기간"
    else:
        year, mon = parse_month(month)
        start, end = month_bounds(year, mon)
        conditions += [IdentityAccessLog.accessed_at >= start, IdentityAccessLog.accessed_at < end]
        month_value = f"{year:04d}-{mon:02d}"
        period_text = month_label(year, mon)
    actor_value = actor if actor.isdigit() else ""
    if actor_value:
        conditions.append(IdentityAccessLog.actor_id == int(actor_value))
    action_value = action if action in AUDIT_ACTION_LABELS else ""
    if action_value:
        conditions.append(IdentityAccessLog.action == action_value)

    count_stmt = tenancy.scoped(
        select(func.count()).select_from(IdentityAccessLog), IdentityAccessLog, user
    )
    list_stmt = tenancy.scoped(select(IdentityAccessLog), IdentityAccessLog, user)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)

    total = db.scalar(count_stmt) or 0
    pages = max(1, -(-total // AUDIT_PAGE_SIZE))
    page_no = min(int(page) if page.isdigit() and int(page) > 0 else 1, pages)
    logs = list(
        db.scalars(
            list_stmt.options(
                selectinload(IdentityAccessLog.actor), selectinload(IdentityAccessLog.case)
            )
            .order_by(IdentityAccessLog.accessed_at.desc(), IdentityAccessLog.id.desc())
            .offset((page_no - 1) * AUDIT_PAGE_SIZE)
            .limit(AUDIT_PAGE_SIZE)
        ).all()
    )

    def page_url(n: int) -> str:
        params = {"month": month_value, "actor": actor_value, "action": action_value, "page": n}
        return "/manage/audit?" + urlencode({k: v for k, v in params.items() if v != ""})

    month_options = recent_months(12)
    if month_value != "all" and month_value not in {value for value, _ in month_options}:
        month_options.append((month_value, period_text))

    return render(
        request,
        "manage/audit.html",
        user,
        "records",
        logs=logs,
        total=total,
        page=page_no,
        pages=pages,
        prev_url=page_url(page_no - 1) if page_no > 1 else None,
        next_url=page_url(page_no + 1) if page_no < pages else None,
        period_text=period_text,
        month_value=month_value,
        month_options=month_options,
        actors=list(
            db.scalars(
                tenancy.scoped(select(User), User, user)
                .where(User.role == Role.MEMBER)
                .order_by(User.role, User.name)
            ).all()
        ),
        actor_value=actor_value,
        action_value=action_value,
        action_labels=AUDIT_ACTION_LABELS,
    )


def _show_temp_password(request: Request, user: User, member: User, temp: str, action: str):
    """임시 비밀번호는 이 응답 하나에만 실어 보낸다.

    리다이렉트하려면 어딘가에 얹어 넘겨야 하고, 그 '어딘가'는 세션 쿠키다 — 서명만 되어
    있어 열어 보면 그대로 읽힌다. 식별정보 열람을 직접 렌더로 바꾼 것과 같은 이유다.
    """
    response = render(
        request,
        "manage/account_issued.html",
        user,
        "manage",
        member=member,
        temp_password=temp,
        action=action,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


@router.post("/members/{member_id}/reset")
def reset_member_password(
    member_id: int, request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)
):
    """비밀번호 초기화.

    관리자가 위원 계정에 들어갈 수 있는 유일한 길이라, 조용히 일어나지 않게 계정 기록에 남긴다.
    초기화된 계정은 첫 로그인에서 비밀번호를 다시 정해야 하므로 위원이 알아차린다.
    """
    member = _member(db, member_id, user)

    temp = accounts.reset_password(db, user, member)
    return _show_temp_password(request, user, member, temp, "reset")


@router.post("/donors/{donor_id}/reset")
def reset_donor_account(
    donor_id: int, request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)
):
    """후원자 숫자 4자리를 전화번호 뒤 네 자리로 초기화한다."""
    donor = _donor(db, donor_id, user)

    try:
        pin = accounts.reset_donor_pin(db, user, donor)
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage/people", status_code=303)

    return _show_temp_password(request, user, donor, pin, "reset_pin")


@router.post("/members/{member_id}/manager")
def transfer_manager(
    member_id: int,
    request: Request,
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """관리자 자리를 다른 위원에게 넘긴다 (2026-10-24 결정).

    협의체당 한 사람이라 넘기면 본인 권한이 사라진다. '부여/해제' 가 아니라 '넘기기' 로
    둔 이유다 — 둘을 따로 두면 두 사람이 관리자인 상태나 아무도 관리자가 아닌 상태를
    만들 수 있고, 뒤쪽은 그 협의체가 아무것도 못 하게 되는 상태다.

    관리자가 갑자기 연락이 안 될 때는 슈퍼 관리자가 교체한다 (/super). 두 길을 다 둔
    것은 한쪽만으로는 공백이 생기기 때문이다.
    """
    member = _member(db, member_id, user)
    if member.id == user.id:
        flash(request, "이미 관리자입니다.")
        return RedirectResponse("/manage/people", status_code=303)
    if not member.is_active:
        flash(request, f"{member.name} 위원은 위촉이 해제된 상태입니다.")
        return RedirectResponse("/manage/people", status_code=303)
    if not member.is_approved:
        flash(request, f"{member.name} 위원을 먼저 승인해 주세요.")
        return RedirectResponse("/manage/people", status_code=303)

    member.is_manager = True
    user.is_manager = False
    accounts.log_event(db, member, "grant_manager", user, "관리자 넘겨받음")
    accounts.log_event(db, user, "revoke_manager", user, f"{member.name} 위원에게 넘김")
    db.commit()

    flash(
        request,
        f"관리자를 {member.name}님에게 넘겼습니다. 이 화면은 더 이상 열리지 않습니다.",
    )
    return RedirectResponse("/member", status_code=303)


@router.post("/members/{member_id}/toggle")
def toggle_member(
    member_id: int, request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)
):
    member = _member(db, member_id, user)

    if member.is_active:
        # 담당 케이스를 남긴 채 해제하면 그 가정은 아무도 손댈 수 없게 된다. 담당 위원만
        # 열 수 있는 식별정보도, 진행 중인 매칭도 함께 잠긴다.
        live = db.scalar(
            tenancy.scoped(select(func.count()).select_from(Case), Case, user).where(
                Case.member_id == member.id, Case.status != CaseStatus.CLOSED
            )
        )
        if live:
            flash(
                request,
                f"{member.name} 위원에게 미종결 케이스 {live}건이 있습니다. "
                "다른 위원에게 인계한 뒤 해제해 주세요.",
            )
            return RedirectResponse("/manage/people", status_code=303)

    member.is_active = not member.is_active
    accounts.log_event(db, member, "reactivate" if member.is_active else "deactivate", user)
    db.commit()
    flash(request, f"{member.name} 위원을 {'위촉 복구' if member.is_active else '위촉 해제'}했습니다.")
    return RedirectResponse("/manage/people", status_code=303)


@router.post("/members/{member_id}/handover")
def handover_cases(
    member_id: int,
    request: Request,
    to_member_id: str = Form(...),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """미종결 케이스를 다른 위원에게 일괄 인계한다.

    관리자가 케이스 '내용'을 보는 건 아니다. 바꾸는 것은 담당자뿐이고, 그 사실은
    열람 기록과 같은 자리에 남는다. 권한 매트릭스의 case_assignment 가 이 경계다.
    """
    member = _member(db, member_id, user)
    to_member = _member(db, int(to_member_id), user) if to_member_id.isdigit() else None
    if to_member is None:
        flash(request, "인계받을 위원을 선택해 주세요.")
        return RedirectResponse("/manage/people", status_code=303)
    if to_member.id == member.id:
        flash(request, "같은 위원에게는 인계할 수 없습니다.")
        return RedirectResponse("/manage/people", status_code=303)
    if not to_member.is_active:
        flash(request, f"{to_member.name} 위원은 위촉이 해제된 상태입니다.")
        return RedirectResponse("/manage/people", status_code=303)

    cases = list(
        db.scalars(
            tenancy.scoped(select(Case), Case, user).where(
                Case.member_id == member.id, Case.status != CaseStatus.CLOSED
            )
        ).all()
    )
    if not cases:
        flash(request, f"{member.name} 위원에게 인계할 미종결 케이스가 없습니다.")
        return RedirectResponse("/manage/people", status_code=303)

    for case in cases:
        case.member_id = to_member.id
        identity_service.log_handover(db, case, user, member, to_member)
    db.commit()

    flash(
        request,
        f"{member.name} 위원의 케이스 {len(cases)}건을 {to_member.name} 위원에게 인계했습니다.",
    )
    return RedirectResponse("/manage/people", status_code=303)


@router.get("/badges")
def badges(request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)):
    shops = list(db.scalars(tenancy.scoped(select(Shop), Shop, user).order_by(Shop.name)).all())
    offer_counts = dict(
        db.execute(
            tenancy.scoped(select(Offer.shop_id, func.count(Offer.id)), Offer, user).group_by(
                Offer.shop_id
            )
        ).all()
    )
    return render(
        request,
        "manage/badges.html",
        user,
        "badges",
        pending=[s for s in shops if not s.is_certified],
        certified=[s for s in shops if s.is_certified],
        offer_counts=offer_counts,
    )


@router.post("/shops/{shop_id}/certify")
def certify_shop(
    shop_id: int,
    request: Request,
    note: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    shop = _shop(db, shop_id, user)
    shop.is_certified = True
    shop.certified_by_id = user.id
    shop.certified_note = note.strip() or f"{datetime.now(KST):%Y-%m-%d} 인증"
    db.commit()
    flash(request, f"{shop.name}에 인증 나눔가게 배지를 부여했습니다.")
    return RedirectResponse("/manage/badges", status_code=303)


@router.post("/shops/{shop_id}/revoke")
def revoke_shop(
    shop_id: int, request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)
):
    shop = _shop(db, shop_id, user)
    shop.is_certified = False
    shop.certified_by_id = None
    db.commit()
    flash(request, f"{shop.name}의 인증을 취소했습니다.")
    return RedirectResponse("/manage/badges", status_code=303)


def _account_events(db: Session, user: User):
    """계정 기록 — 발급·초기화·승인·거절이 남는 자리.

    AccountEvent 에는 council_id 가 없다. 사건의 소속은 그 계정의 소속이기 때문이다.
    그래서 User 를 조인해 경계를 건다 — 조인을 빼면 다른 동의 계정 기록이 그대로 보이고,
    실제로 그랬다 (관리자 화면에서 옮겨 올 때 발견).
    """
    stmt = (
        select(AccountEvent)
        .join(User, AccountEvent.user_id == User.id)
        .options(selectinload(AccountEvent.user), selectinload(AccountEvent.actor))
        .order_by(AccountEvent.created_at.desc(), AccountEvent.id.desc())
        .limit(30)
    )
    return list(db.scalars(tenancy.scoped(stmt, User, user)).all())


def _manage_page(request: Request, db: Session, user: User, **extra):
    """매니저 화면 — 위원이 생기는 두 길, 잠긴 계정, 운영팀 연락처.

    위원 등록을 관리자 화면이 아니라 여기에 둔다. 관리자 = 매니저 = 협의체당 한 사람
    (2026-10-24 결정)이므로, 위원을 들이는 사람과 후원자를 승인하는 사람이 같다.
    """
    council = user.council
    return render(
        request,
        "manage/manage.html",
        user,
        "manage",
        locked=accounts.locked_accounts(db, user),
        policy=retention.current(db, user.council_id),
        max_failed=accounts.MAX_FAILED_LOGINS,
        members=accounts.council_members(db, user),
        pending=invites.pending_members(db, user.council_id),
        codes=invites.listing(db, user.council_id),
        events=_account_events(db, user),
        event_labels=accounts.ACTION_LABELS,
        join_locked=council is not None and council.join_is_locked,
        join_wait_label=council.join_wait_label if council is not None else "",
        # 아직 대기가 걸리지 않은 실패도 보여 준다. 조용히 쌓이다가 갑자기 막히는 것보다
        # "지금 세 번 틀렸습니다" 가 먼저 보이는 쪽이 낫다 — 코드가 새고 있다는 신호다.
        join_failures=(
            council.join_failed_attempts or 0
            if council is not None and not council.join_failures_are_stale
            else 0
        ),
        join_url=f"/c/{council.slug}/join" if council is not None else None,
        max_failed_codes=invites.MAX_FAILED_CODES,
        invite_defaults={"days": DEFAULT_DAYS, "max_uses": DEFAULT_MAX_USES},
        **extra,
    )


@router.get("/people")
def manage(request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)):
    return _manage_page(request, db, user)


@router.post("/invites")
def create_invite(
    request: Request,
    days: str = Form(""),
    max_uses: str = Form(""),
    note: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """초대 코드를 발급한다.

    코드는 임시 비밀번호와 달리 한 번만 보여 주고 숨기지 않는다. 여러 사람에게
    전하는 값이고, 관리자가 "그 코드 뭐였죠" 를 다시 물을 자리가 있어야 한다.
    유효기간·사용 횟수·무효화가 그 대신의 방어다.
    """
    try:
        invite = invites.create(db, user, days=days, max_uses=max_uses, note=note)
    except invites.InviteError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(request, f"초대 코드 {invite.code} 를 발급했습니다.")
    return RedirectResponse("/manage", status_code=303)


@router.post("/invites/{invite_id}/revoke")
def revoke_invite(
    invite_id: int,
    request: Request,
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    invite = db.get(MemberInvite, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="초대 코드를 찾을 수 없습니다.")
    tenancy.assert_same(user, invite)
    try:
        invites.revoke(db, user, invite)
    except invites.InviteError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(request, f"초대 코드 {invite.code} 를 무효화했습니다.")
    return RedirectResponse("/manage", status_code=303)


@router.post("/join/unlock")
def unlock_join(
    request: Request, user: User = Depends(manager_dep), db: Session = Depends(get_db)
):
    try:
        invites.unlock_join(db, user, user.council)
    except invites.InviteError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(request, "위원 가입 대기를 해제했습니다. 지금 바로 가입할 수 있습니다.")
    return RedirectResponse("/manage", status_code=303)


@router.post("/members")
def register_member(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    note: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    """관리자가 대신 등록하는 길 — 임시 비밀번호를 한 번만 보여 준다.

    회의 자리에서 명단을 받아 넣는 경우다. 코드로 가입하는 길과 달리 본인이 화면 앞에
    없으므로 임시 비밀번호를 만들어 전달하고, 첫 로그인에서 본인이 바꾼다.
    """
    try:
        member, temp = accounts.issue_member(db, user, name=name, email=email, note=note)
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    response = _manage_page(
        request, db, user,
        issued={"user": member, "temp": temp},
        flash=f"{member.name}님의 위원 계정을 발급했습니다.",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/members/{member_id}/approve")
def approve_member(
    member_id: int,
    request: Request,
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    target = _account(db, member_id, user)
    try:
        accounts.approve_member(db, user, target)
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(request, f"{target.name}님을 위원으로 승인했습니다. 이제 케이스를 맡을 수 있습니다.")
    return RedirectResponse("/manage", status_code=303)


@router.post("/members/{member_id}/reject")
def reject_member(
    member_id: int,
    request: Request,
    reason: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    target = _account(db, member_id, user)
    try:
        accounts.reject_member(db, user, target, reason)
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(request, f"{target.name}님의 가입을 거절했습니다.")
    return RedirectResponse("/manage", status_code=303)


@router.post("/unlock/{user_id}")
def unlock_account(
    user_id: int,
    request: Request,
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    target = _account(db, user_id, user)
    try:
        accounts.unlock_by_manager(db, user, target)
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    flash(request, f"{target.name}님의 잠금을 해제했습니다.")
    return RedirectResponse("/manage", status_code=303)


@router.post("/contact")
def update_contact(
    request: Request,
    contact: str = Form(""),
    user: User = Depends(manager_dep),
    db: Session = Depends(get_db),
):
    try:
        policy = retention.update_team_contact(db, user, contact)
    except retention.PolicyError as exc:
        flash(request, str(exc))
        return RedirectResponse("/manage", status_code=303)

    if policy.team_contact:
        flash(request, f"운영팀 연락처를 '{policy.team_contact}' 로 저장했습니다.")
    else:
        flash(request, "운영팀 연락처를 비웠습니다. 로그인 화면에 연락처가 뜨지 않습니다.")
    return RedirectResponse("/manage", status_code=303)
