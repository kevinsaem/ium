"""매칭 승인 규칙.

승인 방식이 아직 위원회 미정 안건이라, 판단 로직을 이 파일 하나에 가둬 두었다.
결정이 나면 settings.match_approval_mode 만 바꾸면 되고, 두 모드 모두
MatchApproval 에 감사기록이 남는 건 동일하다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Case,
    CaseStatus,
    Match,
    MatchApproval,
    MatchStatus,
    Offer,
    OfferStatus,
    User,
)


def required_approvals() -> int:
    if settings.match_approval_mode == "member":
        return 1
    return max(1, settings.committee_approvals)


def approval_mode_label() -> str:
    if settings.match_approval_mode == "member":
        return "위원 단독 승인"
    return f"협의체 공동 결정 (위원 {required_approvals()}명 승인)"


def propose(db: Session, case: Case, offer: Offer, member: User, note: str | None = None) -> Match:
    if offer.status is not OfferStatus.OPEN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="이미 매칭 중이거나 종료된 나눔입니다.")
    if case.status in (CaseStatus.RESOLVED, CaseStatus.CLOSED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="종결된 케이스입니다.")

    match = Match(
        case_id=case.id, offer_id=offer.id, proposed_by_id=member.id, note=note,
        status=MatchStatus.PROPOSED,
    )
    db.add(match)
    offer.status = OfferStatus.RESERVED
    case.status = CaseStatus.MATCHING
    db.flush()

    # 제안한 위원의 의사표시도 승인 1표로 기록한다.
    approve(db, match, member, comment="제안 위원 승인", commit=False)
    db.commit()
    db.refresh(match)
    return match


def approve(
    db: Session, match: Match, approver: User, comment: str | None = None, commit: bool = True
) -> Match:
    if match.status is MatchStatus.CANCELLED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="취소된 매칭입니다.")

    already = any(a.approver_id == approver.id for a in match.approvals)
    if not already:
        db.add(
            MatchApproval(
                match_id=match.id,
                approver_id=approver.id,
                comment=comment,
                approved_at=datetime.now(timezone.utc),
            )
        )
        db.flush()
        db.refresh(match)

    if match.status is MatchStatus.PROPOSED and len(match.approvals) >= required_approvals():
        match.status = MatchStatus.APPROVED

    if commit:
        db.commit()
        db.refresh(match)
    return match


def mark_delivered(db: Session, match: Match, actor: User, note: str | None = None) -> Match:
    if match.status is not MatchStatus.APPROVED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"승인 완료된 매칭만 전달 처리할 수 있습니다. (현재: {match.status.label})",
        )
    match.status = MatchStatus.DELIVERED
    match.delivered_at = datetime.now(timezone.utc)
    match.delivery_note = note
    match.offer.status = OfferStatus.CLOSED
    match.case.status = CaseStatus.RESOLVED
    db.commit()
    db.refresh(match)
    return match


def cancel(db: Session, match: Match, actor: User, reason: str | None = None) -> Match:
    if match.status is MatchStatus.DELIVERED:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="이미 전달 완료된 매칭입니다.")
    match.status = MatchStatus.CANCELLED
    match.note = f"{match.note or ''}\n[취소] {reason or ''}".strip()
    match.offer.status = OfferStatus.OPEN
    if not [m for m in match.case.matches if m.status is not MatchStatus.CANCELLED]:
        match.case.status = CaseStatus.OPEN
    db.commit()
    db.refresh(match)
    return match
