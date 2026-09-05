from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import identity_service
from app.db import get_db
from app.deps import require_role
from app.models import (
    Case,
    CaseStatus,
    Credit,
    CreditKind,
    CreditStatus,
    IdentityAccessLog,
    Match,
    MatchStatus,
    Offer,
    Role,
    Shop,
    User,
)
from app.permissions import describe
from app.rendering import flash, render

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
    now = datetime.now(timezone.utc)
    matches = list(db.scalars(select(Match)).all())
    month_delivered = sum(
        1
        for m in matches
        if m.status is MatchStatus.DELIVERED
        and m.delivered_at
        and (m.delivered_at.year, m.delivered_at.month) == (now.year, now.month)
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
            select(IdentityAccessLog).order_by(IdentityAccessLog.accessed_at.desc()).limit(20)
        ).all()
    )

    return render(
        request,
        "office/dash.html",
        user,
        "dash",
        stats=stats,
        goals=goals,
        audit_logs=audit_logs,
        permission_rows=describe(),
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
    return render(
        request,
        "office/members.html",
        user,
        "members",
        members=member_rows,
        donors=donor_rows,
        case_counts=counts,
        open_case_counts=open_counts,
    )


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
    credits = list(
        db.scalars(select(Credit).order_by(Credit.status, Credit.id.desc()).limit(30)).all()
    )
    return render(
        request,
        "office/badges.html",
        user,
        "badges",
        pending=[s for s in shops if not s.is_certified],
        certified=[s for s in shops if s.is_certified],
        offer_counts=offer_counts,
        credits=credits,
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
    shop.certified_note = note.strip() or f"{datetime.now(timezone.utc):%Y-%m-%d} 인증"
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


@router.post("/credits/{credit_id}/process")
def process_credit(
    credit_id: int,
    request: Request,
    decision: str = Form(...),
    note: str = Form(""),
    user: User = Depends(office_dep),
    db: Session = Depends(get_db),
):
    """증빙 발급 판단. 기부금 영수증은 자동 발급하지 않고 운영자가 직접 결정한다."""
    credit = db.get(Credit, credit_id)
    if credit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="증빙 신청을 찾을 수 없습니다.")
    if decision not in ("issued", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="알 수 없는 처리 결과입니다.")

    credit.status = CreditStatus(decision)
    credit.processed_by_id = user.id
    credit.issued_note = note.strip() or None
    if credit.kind is CreditKind.DONATION and credit.status is CreditStatus.ISSUED:
        credit.issued_note = (
            f"{credit.issued_note or ''} (법정기부금단체 요건 확인 완료)".strip()
        )
    db.commit()
    flash(request, f"{credit.donor.name}님의 {credit.kind.label}을 {credit.status.label} 처리했습니다.")
    return RedirectResponse("/office/badges", status_code=303)
