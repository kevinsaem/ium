"""나눔글 노출 심사와 매칭.

위원회 결정(2026-09-19, 안건 05)으로 승인의 자리가 바뀌었다.

    예전: 위원이 케이스↔나눔글을 제안 → 위원 N명이 승인 → 확정
    지금: 후원자가 나눔글을 올림 → 운영팀이 노출 승인 → 위원에게 보임 → 위원이 매칭·전달

승인을 매칭이 아니라 나눔글에 두는 이유는, 협의체 이름으로 나가는 물건을 먼저 거르자는
것이지 어느 가정에 보낼지를 여럿이 정하자는 게 아니기 때문이다. 어느 가정에 보낼지는
그 가정을 아는 담당 위원의 판단으로 남는다.

노출 승인 자체도 번거로워지면 뺄 수 있게 settings.offer_approval 로 열어 두었다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Case, CaseStatus, Match, MatchStatus, Offer, OfferStatus, User


# --- 나눔글 노출 심사 (운영팀) ---------------------------------------------


def initial_offer_status() -> OfferStatus:
    """후원자가 막 올린 나눔글의 상태."""
    return OfferStatus.PENDING if settings.offer_approval else OfferStatus.OPEN


def approval_mode_label() -> str:
    if settings.offer_approval:
        return "운영팀 승인 후 위원에게 노출"
    return "승인 없이 바로 노출"


def _review(
    db: Session, offer: Offer, manager: User, new_status: OfferStatus, note: str | None
) -> Offer:
    offer.status = new_status
    offer.reviewed_by_id = manager.id
    offer.reviewed_at = datetime.now(timezone.utc)
    offer.review_note = note
    db.commit()
    db.refresh(offer)
    return offer


def approve_offer(db: Session, offer: Offer, manager: User, note: str | None = None) -> Offer:
    """노출 승인 — 이때부터 위원의 매칭 후보에 오른다."""
    if offer.status is not OfferStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"승인 대기 중인 나눔글이 아닙니다. (현재: {offer.status.label})",
        )
    return _review(db, offer, manager, OfferStatus.OPEN, note)


def reject_offer(db: Session, offer: Offer, manager: User, note: str) -> Offer:
    """노출 거절.

    사유를 받는 이유는 후원자에게 그대로 보이기 때문이다. 이유 없이 사라지면 후원자는
    앱이 고장 난 줄 알거나, 자기 선의가 거절당했다고만 받아들인다.
    """
    if offer.status is not OfferStatus.PENDING:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"승인 대기 중인 나눔글이 아닙니다. (현재: {offer.status.label})",
        )
    if not note or not note.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="거절 사유를 입력해 주세요.")
    return _review(db, offer, manager, OfferStatus.REJECTED, note.strip())


# --- 매칭 (위원) -----------------------------------------------------------


def propose(db: Session, case: Case, offer: Offer, member: User, note: str | None = None) -> Match:
    """케이스와 나눔글을 잇는다. 별도 승인 단계 없이 바로 확정된다."""
    if offer.status is not OfferStatus.OPEN:
        if offer.status is OfferStatus.PENDING:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="운영팀 승인을 기다리는 나눔입니다."
            )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="이미 매칭 중이거나 종료된 나눔입니다.")
    if case.status in (CaseStatus.RESOLVED, CaseStatus.CLOSED):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="종결된 케이스입니다.")

    match = Match(
        case_id=case.id,
        offer_id=offer.id,
        proposed_by_id=member.id,
        note=note,
        status=MatchStatus.APPROVED,
    )
    db.add(match)
    offer.status = OfferStatus.RESERVED
    case.status = CaseStatus.MATCHING
    db.commit()
    db.refresh(match)
    return match


def mark_delivered(db: Session, match: Match, actor: User, note: str | None = None) -> Match:
    if match.status is not MatchStatus.APPROVED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"진행 중인 매칭만 전달 처리할 수 있습니다. (현재: {match.status.label})",
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
    """매칭 취소 — 나눔글은 다시 위원들의 후보로 돌아간다.

    노출 승인은 이미 끝난 건이라 다시 받지 않는다. 운영팀이 걸러야 할 것은 물건이지
    어느 가정에 갔다가 무산됐는지가 아니다.
    """
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
