from __future__ import annotations

from datetime import datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import accounts, identity_service, matching
from app.config import settings
from app.db import get_db
from app.deps import require_role
from app.models import (
    AccountEvent,
    Case,
    CaseStatus,
    IdentityAccessLog,
    Match,
    MatchStatus,
    Offer,
    OfferStatus,
    Role,
    Shop,
    User,
)
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

router = APIRouter(prefix="/office", dependencies=[Depends(require_role(Role.OFFICE))])
office_dep = require_role(Role.OFFICE)

# 슬라이드 6 안건 ④ 파일럿 성공 지표 — 초안 값. 위원회 확정 시 여기만 고치면 된다.
PILOT_GOALS = [
    {"key": "certified_shops", "label": "인증 나눔가게", "target": 10, "unit": "곳"},
    {"key": "total_matches", "label": "매칭 건수", "target": 20, "unit": "건"},
    {"key": "active_members", "label": "활동 위원", "target": 8, "unit": "명"},
]


@router.get("")
def dashboard(request: Request, user: User = Depends(office_dep), db: Session = Depends(get_db)):
    matches = list(db.scalars(select(Match)).all())
    year, month = current_month()
    month_delivered = sum(
        1 for m in matches if m.status is MatchStatus.DELIVERED and in_month(m.delivered_at, year, month)
    )

    stats = {
        "certified_shops": db.scalar(select(func.count()).select_from(Shop).where(Shop.is_certified)),
        "active_members": db.scalar(
            select(func.count()).select_from(User).where(User.role == Role.MEMBER, User.is_active)
        ),
        "total_matches": len(matches),
        "month_delivered": month_delivered,
        "open_cases": db.scalar(
            select(func.count()).select_from(Case).where(Case.status == CaseStatus.OPEN)
        ),
        "urgent_cases": db.scalar(
            select(func.count())
            .select_from(Case)
            .where(Case.is_urgent, Case.status != CaseStatus.CLOSED)
        ),
    }

    goals = [{**g, "current": stats[g["key"]]} for g in PILOT_GOALS]

    # 운영자는 '열람했다는 사실'만 본다. 열람된 내용은 이 화면에 오지 않는다.
    audit_logs = list(
        db.scalars(
            select(IdentityAccessLog)
            .options(selectinload(IdentityAccessLog.actor), selectinload(IdentityAccessLog.case))
            .order_by(IdentityAccessLog.accessed_at.desc(), IdentityAccessLog.id.desc())
            .limit(5)
        ).all()
    )

    pending_offers = list(
        db.scalars(
            select(Offer)
            .options(selectinload(Offer.shop))
            .where(Offer.status == OfferStatus.PENDING)
            .order_by(Offer.created_at)
        ).all()
    )

    return render(
        request,
        "office/dash.html",
        user,
        "dash",
        pending_offers=pending_offers,
        approval_mode_label=matching.approval_mode_label(),
        stats=stats,
        goals=goals,
        audit_logs=audit_logs,
        permission_rows=describe(),
    )


AUDIT_PAGE_SIZE = 50
AUDIT_ACTION_LABELS = {"read": "열람", "write": "수정", "handover": "담당 변경"}


def _pending_offer(db: Session, offer_id: int) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="나눔글을 찾을 수 없습니다.")
    return offer


@router.post("/offers/{offer_id}/approve")
def approve_offer(
    offer_id: int,
    request: Request,
    note: str = Form(""),
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    """나눔글 노출 승인 (위원회 결정, 안건 05).

    협의체 이름으로 전달되는 물건이라 운영팀이 먼저 본다. 승인하면 위원들의 매칭 후보에 오른다.
    """
    offer = _pending_offer(db, offer_id)
    matching.approve_offer(db, offer, user, note.strip() or None)
    flash(request, f"'{offer.title}' 을(를) 승인했습니다. 위원들에게 노출됩니다.")
    return RedirectResponse("/office", status_code=303)


@router.post("/offers/{offer_id}/reject")
def reject_offer(
    offer_id: int,
    request: Request,
    note: str = Form(""),
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    """노출 거절 — 사유는 후원자에게 그대로 보인다."""
    offer = _pending_offer(db, offer_id)
    if not note.strip():
        flash(request, "거절 사유를 입력해 주세요. 후원자에게 그대로 전달됩니다.")
        return RedirectResponse("/office", status_code=303)

    matching.reject_offer(db, offer, user, note)
    flash(request, f"'{offer.title}' 을(를) 노출하지 않기로 했습니다.")
    return RedirectResponse("/office", status_code=303)


@router.get("/report")
def report(
    request: Request, month: str = "", user: User = Depends(office_dep), db: Session = Depends(get_db)
):
    """동 전체 월간 보고서와 미종결 케이스 현황.

    위원 개인 보고서와 같은 계산(app/reporting.py)을 동 전체에 적용한다. 운영자가 보는 것은
    비식별 코드와 진행 상태뿐이고, 식별정보는 '보관 중인지'만 드러난다.
    """
    year, mon = parse_month(month)
    cases = list(
        db.scalars(select(Case).options(selectinload(Case.member), selectinload(Case.identity))).all()
    )
    matches = list(
        db.scalars(
            select(Match).options(
                selectinload(Match.case).selectinload(Case.member),
                selectinload(Match.offer).selectinload(Offer.shop),
            )
        ).all()
    )
    monthly = build_monthly_report(
        cases, matches, year, mon, [f"작성: {settings.dong} 지역사회보장협의체"], by_member=True
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

    prev_y, prev_m = shift_month(year, mon, -1)
    next_y, next_m = shift_month(year, mon, 1)
    has_next = (next_y, next_m) <= current_month()
    return render(
        request,
        "office/report.html",
        user,
        "records",
        report=monthly,
        open_rows=open_rows,
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
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    """식별정보 접근 감사 기록 전체.

    대시보드의 최근 몇 건으로는 '지난달 누가 무엇을 열었나'에 답할 수 없다. 운영자의
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

    count_stmt = select(func.count()).select_from(IdentityAccessLog)
    list_stmt = select(IdentityAccessLog)
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
        return "/office/audit?" + urlencode({k: v for k, v in params.items() if v != ""})

    month_options = recent_months(12)
    if month_value != "all" and month_value not in {value for value, _ in month_options}:
        month_options.append((month_value, period_text))

    return render(
        request,
        "office/audit.html",
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
                select(User)
                .where(User.role.in_([Role.MEMBER, Role.OFFICE]))
                .order_by(User.role, User.name)
            ).all()
        ),
        actor_value=actor_value,
        action_value=action_value,
        action_labels=AUDIT_ACTION_LABELS,
    )


@router.get("/members")
def members(request: Request, user: User = Depends(office_dep), db: Session = Depends(get_db)):
    member_rows = list(
        db.scalars(select(User).where(User.role == Role.MEMBER).order_by(User.name)).all()
    )
    donor_rows = list(
        db.scalars(select(User).where(User.role == Role.DONOR).order_by(User.name)).all()
    )
    counts = dict(
        db.execute(select(Case.member_id, func.count(Case.id)).group_by(Case.member_id)).all()
    )
    # 위촉 해제의 실제 걸림돌은 '아직 살아 있는 케이스'다. 종결된 건 인계할 필요가 없다.
    open_counts = dict(
        db.execute(
            select(Case.member_id, func.count(Case.id))
            .where(Case.status != CaseStatus.CLOSED)
            .group_by(Case.member_id)
        ).all()
    )
    events = list(
        db.scalars(
            select(AccountEvent)
            .options(selectinload(AccountEvent.user), selectinload(AccountEvent.actor))
            .order_by(AccountEvent.created_at.desc(), AccountEvent.id.desc())
            .limit(30)
        ).all()
    )
    return render(
        request,
        "office/members.html",
        user,
        "members",
        members=member_rows,
        donors=donor_rows,
        case_counts=counts,
        open_case_counts=open_counts,
        events=events,
        event_labels=accounts.ACTION_LABELS,
    )


def _show_temp_password(request: Request, user: User, member: User, temp: str, action: str):
    """임시 비밀번호는 이 응답 하나에만 실어 보낸다.

    리다이렉트하려면 어딘가에 얹어 넘겨야 하고, 그 '어딘가'는 세션 쿠키다 — 서명만 되어 있어
    열어 보면 그대로 읽힌다. 식별정보 열람을 직접 렌더로 바꾼 것과 같은 이유다.
    """
    response = render(
        request,
        "office/account_issued.html",
        user,
        "members",
        member=member,
        temp_password=temp,
        action=action,
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"
    return response


@router.post("/members")
def issue_member_account(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    note: str = Form(""),
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    """위원 계정 발급 — 위촉과 함께 운영자가 만든다 (위원회 안건 07)."""
    try:
        member, temp = accounts.issue_member(
            db, user, name=name, email=email, note=note.strip() or None
        )
    except accounts.AccountError as exc:
        flash(request, str(exc))
        return RedirectResponse("/office/members", status_code=303)

    return _show_temp_password(request, user, member, temp, "issue")


@router.post("/members/{member_id}/reset")
def reset_member_password(
    member_id: int, request: Request, user: User = Depends(office_dep), db: Session = Depends(get_db)
):
    """비밀번호 초기화.

    운영자가 위원 계정에 들어갈 수 있는 유일한 길이라, 조용히 일어나지 않게 계정 기록에 남긴다.
    초기화된 계정은 첫 로그인에서 비밀번호를 다시 정해야 하므로 위원이 알아차린다.
    """
    member = db.get(User, member_id)
    if member is None or member.role is not Role.MEMBER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="위원을 찾을 수 없습니다.")

    temp = accounts.reset_password(db, user, member)
    return _show_temp_password(request, user, member, temp, "reset")


@router.post("/members/{member_id}/toggle")
def toggle_member(
    member_id: int, request: Request, user: User = Depends(office_dep), db: Session = Depends(get_db)
):
    member = db.get(User, member_id)
    if member is None or member.role is not Role.MEMBER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="위원을 찾을 수 없습니다.")

    if member.is_active:
        # 담당 케이스를 남긴 채 해제하면 그 가정은 아무도 손댈 수 없게 된다. 담당 위원만
        # 열 수 있는 식별정보도, 진행 중인 매칭도 함께 잠긴다.
        live = db.scalar(
            select(func.count())
            .select_from(Case)
            .where(Case.member_id == member.id, Case.status != CaseStatus.CLOSED)
        )
        if live:
            flash(
                request,
                f"{member.name} 위원에게 미종결 케이스 {live}건이 있습니다. "
                "다른 위원에게 인계한 뒤 해제해 주세요.",
            )
            return RedirectResponse("/office/members", status_code=303)

    member.is_active = not member.is_active
    accounts.log_event(db, member, "reactivate" if member.is_active else "deactivate", user)
    db.commit()
    flash(request, f"{member.name} 위원을 {'위촉 복구' if member.is_active else '위촉 해제'}했습니다.")
    return RedirectResponse("/office/members", status_code=303)


@router.post("/members/{member_id}/handover")
def handover_cases(
    member_id: int,
    request: Request,
    to_member_id: str = Form(...),
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    """미종결 케이스를 다른 위원에게 일괄 인계한다.

    운영자가 케이스 '내용'을 보는 건 아니다. 바꾸는 것은 담당자뿐이고, 그 사실은
    열람 기록과 같은 자리에 남는다. 권한 매트릭스의 case_assignment 가 이 경계다.
    """
    member = db.get(User, member_id)
    to_member = db.get(User, int(to_member_id)) if to_member_id.isdigit() else None
    if member is None or member.role is not Role.MEMBER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="위원을 찾을 수 없습니다.")
    if to_member is None or to_member.role is not Role.MEMBER:
        flash(request, "인계받을 위원을 선택해 주세요.")
        return RedirectResponse("/office/members", status_code=303)
    if to_member.id == member.id:
        flash(request, "같은 위원에게는 인계할 수 없습니다.")
        return RedirectResponse("/office/members", status_code=303)
    if not to_member.is_active:
        flash(request, f"{to_member.name} 위원은 위촉이 해제된 상태입니다.")
        return RedirectResponse("/office/members", status_code=303)

    cases = list(
        db.scalars(
            select(Case).where(Case.member_id == member.id, Case.status != CaseStatus.CLOSED)
        ).all()
    )
    if not cases:
        flash(request, f"{member.name} 위원에게 인계할 미종결 케이스가 없습니다.")
        return RedirectResponse("/office/members", status_code=303)

    for case in cases:
        case.member_id = to_member.id
        identity_service.log_handover(db, case, user, member, to_member)
    db.commit()

    flash(
        request,
        f"{member.name} 위원의 케이스 {len(cases)}건을 {to_member.name} 위원에게 인계했습니다.",
    )
    return RedirectResponse("/office/members", status_code=303)


@router.get("/badges")
def badges(request: Request, user: User = Depends(office_dep), db: Session = Depends(get_db)):
    shops = list(db.scalars(select(Shop).order_by(Shop.name)).all())
    offer_counts = dict(
        db.execute(select(Offer.shop_id, func.count(Offer.id)).group_by(Offer.shop_id)).all()
    )
    return render(
        request,
        "office/badges.html",
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
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="가게를 찾을 수 없습니다.")
    shop.is_certified = True
    shop.certified_by_id = user.id
    shop.certified_note = note.strip() or f"{datetime.now(KST):%Y-%m-%d} 인증"
    db.commit()
    flash(request, f"{shop.name}에 인증 나눔가게 배지를 부여했습니다.")
    return RedirectResponse("/office/badges", status_code=303)


@router.post("/shops/{shop_id}/revoke")
def revoke_shop(
    shop_id: int, request: Request, user: User = Depends(office_dep), db: Session = Depends(get_db)
):
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="가게를 찾을 수 없습니다.")
    shop.is_certified = False
    shop.certified_by_id = None
    db.commit()
    flash(request, f"{shop.name}의 인증을 취소했습니다.")
    return RedirectResponse("/office/badges", status_code=303)
