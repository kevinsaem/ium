"""매칭.

위원회 결정으로 승인의 자리가 두 번 옮겨졌다.

    1차(안건 05): 위원이 케이스↔나눔글을 제안 → 위원 N명 승인 → 확정
    2차(안건 10): 나눔글 건건이 심사하는 방식을 폐기 → 후원자 자체를 검증

지금은 이렇게 돈다.

    위원이 후원자를 발굴해 계정을 만든다 → 매니저가 후원자를 승인한다
    → 그 후원자의 나눔글은 바로 위원의 매칭 후보에 오른다 → 위원이 매칭·전달한다

거르는 대상이 물건에서 사람으로 바뀐 것이다. 물건을 건건이 보는 일은 "번거롭다"는 것이
폐기 이유였고, 후원자를 한 번 보면 그 사람이 내놓는 것 전체가 함께 걸러진다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, CaseStatus, Match, MatchStatus, Offer, OfferStatus, User


# --- 매칭 (위원) -----------------------------------------------------------


def propose(db: Session, case: Case, offer: Offer, member: User, note: str | None = None) -> Match:
    """케이스와 나눔글을 잇는다. 별도 승인 단계 없이 바로 확정된다."""
    if not offer.shop.owner.is_approved:
        # 미승인 후원자의 나눔글은 후보 목록에 오르지 않지만, 주소를 직접 넣는 길이 있어
        # 여기서도 막는다. 승인 단계가 있으나 마나가 되면 안 된다.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="아직 승인되지 않은 후원자의 나눔입니다."
        )
    if offer.status is not OfferStatus.OPEN:
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
    """매칭 취소 — 나눔글은 다시 위원들의 후보로 돌아간다."""
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


def open_offers_for_members(db: Session):
    """위원의 매칭 후보 — 승인된 후원자의 '나눔 가능' 글만.

    이 조건을 화면마다 따로 쓰면 한 곳만 고쳐지고 다른 곳으로 미승인 후원자의 글이 샌다.
    """
    from app.models import Shop

    return list(
        db.scalars(
            select(Offer)
            .join(Shop, Offer.shop_id == Shop.id)
            .join(User, Shop.owner_id == User.id)
            .where(Offer.status == OfferStatus.OPEN, User.approved_at.is_not(None))
            .order_by(Offer.created_at.desc())
        ).all()
    )
