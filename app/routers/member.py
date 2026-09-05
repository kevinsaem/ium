from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import identity_service, matching
from app.db import get_db
from app.deps import require_role
from app.models import (
    Case,
    CaseStatus,
    IdentityAccessLog,
    Match,
    MatchStatus,
    Offer,
    OfferStatus,
    Role,
    Shop,
    ThanksMessage,
    User,
)
from app.rendering import flash, render

router = APIRouter(prefix="/member", dependencies=[Depends(require_role(Role.MEMBER))])
member_dep = require_role(Role.MEMBER)


def _own_case(db: Session, case_id: int, user: User) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="케이스를 찾을 수 없습니다.")
    if case.member_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="담당 위원만 접근할 수 있습니다.")
    return case


def _own_match(db: Session, match_id: int, user: User) -> Match:
    """매칭에 손대는 건 그 케이스의 담당 위원이다.

    승인은 정족수를 위해 다른 위원에게도 열려 있지만, 전달과 취소는 실제로 가정을
    만나는 사람의 판단이다. 담당이 아닌 위원이 남의 가정 일을 종결시킬 수는 없다.
    """
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="매칭을 찾을 수 없습니다.")
    if match.case.member_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="담당 위원만 처리할 수 있습니다.")
    return match


@router.get("")
def cases(request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)):
    rows = list(
        db.scalars(
            select(Case)
            .where(Case.member_id == user.id)
            .order_by(Case.is_urgent.desc(), Case.created_at.desc())
        ).all()
    )
    return render(request, "member/cases.html", user, "cases", cases=rows)


@router.post("/cases")
def create_case(
    request: Request,
    code: str = Form(...),
    need_summary: str = Form(...),
    situation_note: str = Form(""),
    household_size: str = Form(""),
    is_urgent: str = Form(""),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    code = code.strip()
    if db.scalar(select(Case).where(Case.code == code)) is not None:
        flash(request, f"'{code}' 코드는 이미 사용 중입니다. 다른 코드를 쓰세요.")
        return RedirectResponse("/member", status_code=303)

    case = Case(
        code=code,
        need_summary=need_summary.strip(),
        situation_note=situation_note.strip() or None,
        household_size=int(household_size) if household_size.strip().isdigit() else None,
        is_urgent=bool(is_urgent),
        member_id=user.id,
    )
    db.add(case)
    db.commit()
    flash(request, "케이스가 등록되었습니다. 식별정보는 상세 화면에서 따로 저장하세요.")
    return RedirectResponse(f"/member/cases/{case.id}", status_code=303)


def _case_detail(
    request: Request,
    db: Session,
    user: User,
    case: Case,
    identity: dict[str, str | None] | None = None,
):
    """케이스 상세 화면.

    identity 는 열람 요청(POST reveal)이 방금 복호화한 값일 때만 채워진다. 저장하지 않고
    이 응답 하나에만 실어 보낸다 — 세션에 담으면 쿠키를 타고 브라우저에 남는다.
    """
    open_offers = list(
        db.scalars(select(Offer).join(Shop).where(Offer.status == OfferStatus.OPEN)).all()
    )
    logs = list(
        db.scalars(
            select(IdentityAccessLog)
            .where(IdentityAccessLog.case_id == case.id)
            .order_by(IdentityAccessLog.accessed_at.desc())
            .limit(10)
        ).all()
    )

    response = render(
        request,
        "member/case_detail.html",
        user,
        "cases",
        case=case,
        identity=identity,
        access_logs=logs,
        open_offers=open_offers,
        required_approvals=matching.required_approvals(),
        approval_mode_label=matching.approval_mode_label(),
    )
    if identity is not None:
        # 복호화된 화면은 디스크 캐시·프록시·뒤로가기에 남기지 않는다.
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
        response.headers["Pragma"] = "no-cache"
    return response


@router.get("/cases/{case_id}")
def case_detail(
    case_id: int, request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)
):
    return _case_detail(request, db, user, _own_case(db, case_id, user))


@router.post("/cases/{case_id}/identity")
def save_identity(
    case_id: int,
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    address: str = Form(""),
    consult_note: str = Form(""),
    consent_note: str = Form(""),
    consent_given: str = Form(""),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    case = _own_case(db, case_id, user)
    identity_service.upsert_identity(
        db,
        case,
        user,
        name=name.strip() or None,
        phone=phone.strip() or None,
        address=address.strip() or None,
        consult_note=consult_note.strip() or None,
        consent_note=consent_note.strip() or None,
        consent_given=bool(consent_given),
    )
    flash(request, "식별정보를 암호화하여 저장했습니다. 저장 사실이 기록되었습니다.")
    return RedirectResponse(f"/member/cases/{case_id}", status_code=303)


@router.post("/cases/{case_id}/identity/reveal")
def reveal_identity(
    case_id: int,
    request: Request,
    reason: str = Form(...),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    case = _own_case(db, case_id, user)
    data = identity_service.read_identity(db, case, user, reason)
    consent_at = data.get("consent_obtained_at")
    identity = {
        "name": data["name"],
        "phone": data["phone"],
        "address": data["address"],
        "consult_note": data["consult_note"],
        "consent_obtained_at": consent_at.strftime("%Y-%m-%d") if consent_at else None,
        "consent_note": data.get("consent_note"),
    }
    # 리다이렉트하지 않고 여기서 바로 그린다. 리다이렉트하려면 복호화된 값을 어딘가에
    # 얹어 넘겨야 하고, 그 '어딘가'가 세션 쿠키였다.
    return _case_detail(request, db, user, case, identity)


@router.post("/cases/{case_id}/identity/purge")
def purge_identity(
    case_id: int,
    request: Request,
    reason: str = Form("케이스 종결"),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    case = _own_case(db, case_id, user)
    identity_service.purge_identity(db, case, user, reason)
    flash(request, "식별정보를 파기했습니다. 비식별 케이스 기록과 통계는 그대로 남습니다.")
    return RedirectResponse(f"/member/cases/{case_id}", status_code=303)


@router.post("/cases/{case_id}/public-support")
def set_public_support(
    case_id: int,
    request: Request,
    linked: str = Form(""),
    note: str = Form(""),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    case = _own_case(db, case_id, user)
    case.public_support_linked = bool(linked)
    case.public_support_note = note.strip() or None
    db.commit()
    flash(request, "공적지원 연계 상태를 저장했습니다.")
    return RedirectResponse(f"/member/cases/{case_id}", status_code=303)


@router.post("/cases/{case_id}/close")
def close_case(
    case_id: int, request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)
):
    """케이스 종결.

    진행 중인 매칭이 있으면 종결하지 않는다. 후원자에게는 '갑니다'라고 해 두고 받는 쪽만
    닫아 버리면 그 나눔은 갈 곳을 잃는다. 매칭을 먼저 정리해야 한다.
    """
    case = _own_case(db, case_id, user)
    live = [m for m in case.matches if m.status in (MatchStatus.PROPOSED, MatchStatus.APPROVED)]
    if live:
        flash(request, "진행 중인 매칭이 있습니다. 전달 완료나 취소로 정리한 뒤 종결해 주세요.")
        return RedirectResponse(f"/member/cases/{case_id}", status_code=303)
    if case.status is CaseStatus.CLOSED:
        flash(request, "이미 종결된 케이스입니다.")
        return RedirectResponse(f"/member/cases/{case_id}", status_code=303)

    case.status = CaseStatus.CLOSED
    db.commit()
    if case.has_identity:
        # 종결이 곧 파기는 아니다. 파기는 되돌릴 수 없으므로 위원이 직접 눌러야 한다.
        flash(request, "케이스를 종결했습니다. 식별정보가 아직 남아 있습니다 — 파기해 주세요.")
    else:
        flash(request, "케이스를 종결했습니다.")
    return RedirectResponse(f"/member/cases/{case_id}", status_code=303)


@router.post("/cases/{case_id}/reopen")
def reopen_case(
    case_id: int, request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)
):
    """종결 되돌리기 — 같은 가정에 상황이 다시 생겼을 때.

    식별정보를 이미 파기했다면 되돌려도 비식별 케이스로만 남는다. 그 편이 맞다.
    """
    case = _own_case(db, case_id, user)
    if case.status is not CaseStatus.CLOSED:
        flash(request, "종결된 케이스가 아닙니다.")
        return RedirectResponse(f"/member/cases/{case_id}", status_code=303)

    case.status = CaseStatus.OPEN
    db.commit()
    if case.has_identity:
        flash(request, "종결을 되돌렸습니다.")
    else:
        flash(request, "종결을 되돌렸습니다. 식별정보는 파기되어 다시 등록해야 합니다.")
    return RedirectResponse(f"/member/cases/{case_id}", status_code=303)


@router.post("/matches")
def propose_match(
    request: Request,
    case_id: int = Form(...),
    offer_id: int = Form(...),
    note: str = Form(""),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    case = _own_case(db, case_id, user)
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="나눔글을 찾을 수 없습니다.")

    match = matching.propose(db, case, offer, user, note.strip() or None)
    if match.status is MatchStatus.APPROVED:
        flash(request, "매칭이 승인되었습니다. 전달 후 완료 처리해 주세요.")
    else:
        flash(
            request,
            f"매칭을 제안했습니다. {matching.required_approvals()}명 승인이 모이면 확정됩니다.",
        )
    return RedirectResponse(f"/member/cases/{case_id}", status_code=303)


@router.get("/matches")
def match_board(request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)):
    all_matches = list(db.scalars(select(Match).order_by(Match.created_at.desc())).all())
    my_approved = {
        m.id for m in all_matches if any(a.approver_id == user.id for a in m.approvals)
    }
    return render(
        request,
        "member/match.html",
        user,
        "match",
        pending=[m for m in all_matches if m.status is MatchStatus.PROPOSED],
        approved=[m for m in all_matches if m.status is MatchStatus.APPROVED],
        delivered=[m for m in all_matches if m.status is MatchStatus.DELIVERED],
        my_approved=my_approved,
        # 전달·취소 버튼은 담당 위원에게만 보인다 (라우트에서도 다시 막는다).
        my_cases={m.id for m in all_matches if m.case.member_id == user.id},
        required_approvals=matching.required_approvals(),
        approval_mode_label=matching.approval_mode_label(),
    )


@router.post("/matches/{match_id}/approve")
def approve_match(
    match_id: int, request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)
):
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="매칭을 찾을 수 없습니다.")
    matching.approve(db, match, user)
    if match.status is MatchStatus.APPROVED:
        flash(request, "정족수가 채워져 매칭이 확정되었습니다.")
    else:
        remaining = matching.required_approvals() - match.approval_count
        flash(request, f"승인했습니다. {remaining}명의 승인이 더 필요합니다.")
    return RedirectResponse("/member/matches", status_code=303)


@router.post("/matches/{match_id}/deliver")
def deliver_match(
    match_id: int,
    request: Request,
    note: str = Form(""),
    thanks: str = Form(""),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    match = _own_match(db, match_id, user)

    matching.mark_delivered(db, match, user, note.strip() or None)
    if thanks.strip():
        db.add(
            ThanksMessage(
                match_id=match.id,
                written_by_id=user.id,
                body=thanks.strip(),
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
    flash(request, "전달 완료로 기록했습니다.")
    return RedirectResponse("/member/matches", status_code=303)


@router.post("/matches/{match_id}/cancel")
def cancel_match(
    match_id: int,
    request: Request,
    reason: str = Form(...),
    user: User = Depends(member_dep),
    db: Session = Depends(get_db),
):
    """매칭 취소 — 나눔을 후원자에게 돌려주고 케이스를 다시 열어 둔다.

    사유를 받는 이유는 열람 사유와 같다. 취소는 후원자에게 '안 갑니다'라고 말하는 일이고,
    그 판단의 근거가 match.note 에 남아야 나중에 설명할 수 있다.
    """
    match = _own_match(db, match_id, user)
    if not reason.strip():
        flash(request, "취소 사유를 입력해 주세요.")
        return RedirectResponse("/member/matches", status_code=303)

    matching.cancel(db, match, user, reason.strip())
    flash(request, "매칭을 취소했습니다. 나눔글은 다시 '나눔 가능'으로 돌아갑니다.")
    return RedirectResponse("/member/matches", status_code=303)


@router.get("/report")
def report(request: Request, user: User = Depends(member_dep), db: Session = Depends(get_db)):
    """월간 활동 보고서 초안 — 비식별 코드만으로 생성된다."""
    now = datetime.now(timezone.utc)
    my_cases = list(db.scalars(select(Case).where(Case.member_id == user.id)).all())
    case_ids = [c.id for c in my_cases]

    matches = (
        list(db.scalars(select(Match).where(Match.case_id.in_(case_ids))).all()) if case_ids else []
    )
    delivered = [
        m
        for m in matches
        if m.status is MatchStatus.DELIVERED
        and m.delivered_at
        and (m.delivered_at.year, m.delivered_at.month) == (now.year, now.month)
    ]

    summary = {
        "cases": len(my_cases),
        "matches": len(matches),
        "delivered": len(delivered),
        "urgent": sum(1 for c in my_cases if c.is_urgent),
        "public_support": sum(1 for c in my_cases if c.public_support_linked),
        "shops": len({m.offer.shop_id for m in delivered}),
    }
    period_label = f"{now.year}년 {now.month}월"

    lines = [
        f"보고 기간: {period_label}",
        f"담당 위원: {user.name}",
        "",
        f"1. 발굴 케이스 {summary['cases']}건 (긴급 {summary['urgent']}건)",
        f"2. 매칭 제안 {summary['matches']}건, 이 중 당월 전달 완료 {summary['delivered']}건",
        f"3. 참여 나눔가게 {summary['shops']}곳",
        f"4. 공적지원 연계 {summary['public_support']}건",
        "",
        "당월 전달 내역:",
    ]
    lines += [
        f"  - {m.case.code} / {m.case.need_summary} ← {m.offer.title} ({m.offer.shop.name})"
        for m in delivered
    ] or ["  - 없음"]
    lines += ["", "※ 본 보고서는 비식별 코드만 사용하여 자동 생성되었습니다."]

    return render(
        request,
        "member/report.html",
        user,
        "report",
        summary=summary,
        delivered=delivered,
        period_label=period_label,
        report_text="\n".join(lines),
    )
