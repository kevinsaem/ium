from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import require_role
from app.forms import parse_enum
from app.icons import KIND_ICON
from app.models import (
    Credit,
    CreditKind,
    DeliveryMethod,
    Match,
    MatchStatus,
    Offer,
    OfferKind,
    OfferStatus,
    Role,
    Shop,
    ThanksMessage,
    User,
)
from app.rendering import flash, render

router = APIRouter(prefix="/donor", dependencies=[Depends(require_role(Role.DONOR))])
donor_dep = require_role(Role.DONOR)


def _shop(db: Session, user: User) -> Shop | None:
    return db.scalar(select(Shop).where(Shop.owner_id == user.id))


def _own_offer(db: Session, offer_id: int, user: User) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="나눔글을 찾을 수 없습니다.")
    if offer.shop.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="본인이 올린 나눔글만 관리할 수 있습니다.")
    return offer


@router.get("")
def feed(request: Request, user: User = Depends(donor_dep), db: Session = Depends(get_db)):
    """나눔 피드 — 동네 전체의 나눔글. 대상자 정보는 어디에도 없다."""
    offers = list(
        db.scalars(
            select(Offer).join(Shop).order_by(Offer.status, Offer.created_at.desc())
        ).all()
    )
    return render(request, "donor/feed.html", user, "feed", offers=offers)


@router.get("/offers/{offer_id}")
def offer_detail(
    offer_id: int, request: Request, user: User = Depends(donor_dep), db: Session = Depends(get_db)
):
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="나눔글을 찾을 수 없습니다.")

    thanks: list[ThanksMessage] = []
    if offer.shop.owner_id == user.id:
        match_ids = [m.id for m in offer.matches]
        if match_ids:
            thanks = list(
                db.scalars(select(ThanksMessage).where(ThanksMessage.match_id.in_(match_ids))).all()
            )

    return render(request, "donor/offer_detail.html", user, "feed", offer=offer, thanks=thanks)


@router.get("/post")
def post_form(request: Request, user: User = Depends(donor_dep), db: Session = Depends(get_db)):
    return render(
        request,
        "donor/post.html",
        user,
        "post",
        shop=_shop(db, user),
        offer_kinds=list(OfferKind),
        delivery_methods=list(DeliveryMethod),
    )


@router.post("/shop")
def create_shop(
    request: Request,
    name: str = Form(...),
    category: str = Form(""),
    address: str = Form(""),
    walk_minutes: str = Form(""),
    user: User = Depends(donor_dep),
    db: Session = Depends(get_db),
):
    if _shop(db, user) is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="이미 등록된 가게가 있습니다.")

    db.add(
        Shop(
            owner_id=user.id,
            name=name.strip(),
            category=category.strip() or None,
            address=address.strip() or None,
            walk_minutes=int(walk_minutes) if walk_minutes.strip().isdigit() else None,
        )
    )
    db.commit()
    flash(request, "가게가 등록되었습니다. 운영자 인증 후 배지가 부여됩니다.")
    return RedirectResponse("/donor/post", status_code=303)


@router.post("/offers")
def create_offer(
    request: Request,
    title: str = Form(...),
    kind: str = Form(...),
    quantity_note: str = Form(""),
    delivery: str = Form(...),
    detail: str = Form(""),
    user: User = Depends(donor_dep),
    db: Session = Depends(get_db),
):
    shop = _shop(db, user)
    if shop is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="가게를 먼저 등록해주세요.")

    offer_kind = parse_enum(OfferKind, kind, "나눔 종류")
    db.add(
        Offer(
            shop_id=shop.id,
            title=title.strip(),
            kind=offer_kind,
            icon=KIND_ICON.get(offer_kind.value, "bag"),
            quantity_note=quantity_note.strip() or None,
            delivery=parse_enum(DeliveryMethod, delivery, "전달 방법"),
            detail=detail.strip() or None,
        )
    )
    db.commit()
    flash(request, "나눔글이 등록되었습니다. 위원이 필요한 곳에 연결해 드립니다.")
    return RedirectResponse("/donor", status_code=303)


@router.get("/mine")
def mine(request: Request, user: User = Depends(donor_dep), db: Session = Depends(get_db)):
    shop = _shop(db, user)
    offers = (
        list(
            db.scalars(
                select(Offer)
                .where(Offer.shop_id == shop.id)
                # 나눔지수가 match.case.is_urgent 를 읽으므로 여기서 함께 당겨 온다.
                .options(selectinload(Offer.matches).selectinload(Match.case))
                .order_by(Offer.created_at.desc())
            ).all()
        )
        if shop
        else []
    )

    delivered = [m for o in offers for m in o.matches if m.status is MatchStatus.DELIVERED]

    # 나눔글별 진행 상황은 '상태 라벨'만 넘긴다. Case 는 권한 매트릭스상 위원·운영자만
    # 읽을 수 있으므로, 후원자 템플릿에 Match 객체를 통째로 넘기지 않는다.
    match_state = {}
    for offer in offers:
        live = next((m for m in offer.matches if m.status is not MatchStatus.CANCELLED), None)
        match_state[offer.id] = live.status.label if live else None

    # 마감을 되돌릴 수 있는 건 전달까지 가지 않은 나눔글뿐이다 (전달 기록은 실적의 근거).
    reopenable = {
        o.id: o.status is OfferStatus.CLOSED
        and not any(m.status is MatchStatus.DELIVERED for m in o.matches)
        for o in offers
    }

    now = datetime.now(timezone.utc)
    this_month = sum(
        1
        for m in delivered
        if m.delivered_at and (m.delivered_at.year, m.delivered_at.month) == (now.year, now.month)
    )

    thanks = (
        list(
            db.scalars(
                select(ThanksMessage).where(ThanksMessage.match_id.in_([m.id for m in delivered]))
            ).all()
        )
        if delivered
        else []
    )
    credits = list(
        db.scalars(select(Credit).where(Credit.donor_id == user.id).order_by(Credit.id.desc())).all()
    )

    return render(
        request,
        "donor/mine.html",
        user,
        "mine",
        shop=shop,
        offers=offers,
        match_state=match_state,
        reopenable=reopenable,
        credits=credits,
        thanks=thanks,
        period_label=f"{now.year}년",
        stats={
            "total": len(delivered),
            # 나눔지수: 전달 완료 건수에 긴급 케이스 가중치를 얹은 단순 지표
            "score": sum(3 if m.case.is_urgent else 2 for m in delivered),
            "this_month": this_month,
        },
    )


@router.post("/offers/{offer_id}/close")
def close_offer(
    offer_id: int, request: Request, user: User = Depends(donor_dep), db: Session = Depends(get_db)
):
    """소진·마감 처리.

    위원이 매칭을 진행 중인(RESERVED) 나눔은 후원자가 임의로 내릴 수 없다. 위원은 이미
    특정 가정에 '이건 갑니다'라고 말한 상태이고, 그 약속을 앱이 조용히 깨서는 안 된다.
    """
    offer = _own_offer(db, offer_id, user)
    # 막힌 이유는 오류가 아니라 안내다. 후원자 입장에서는 정상적인 상황이고,
    # 돌아갈 화면도 '내 나눔글' 하나로 정해져 있다.
    if offer.status is OfferStatus.RESERVED:
        flash(request, "위원이 매칭을 진행 중입니다. 담당 위원에게 알려 매칭을 먼저 취소해 주세요.")
        return RedirectResponse("/donor/mine", status_code=303)
    if offer.status is OfferStatus.CLOSED:
        flash(request, "이미 종료된 나눔글입니다.")
        return RedirectResponse("/donor/mine", status_code=303)

    offer.status = OfferStatus.CLOSED
    db.commit()
    flash(request, f"'{offer.title}' 을(를) 마감했습니다. 위원의 매칭 후보에서 빠집니다.")
    return RedirectResponse("/donor/mine", status_code=303)


@router.post("/offers/{offer_id}/reopen")
def reopen_offer(
    offer_id: int, request: Request, user: User = Depends(donor_dep), db: Session = Depends(get_db)
):
    """마감 되돌리기 — 실수로 내린 경우를 위한 것이다.

    전달까지 끝난 나눔글은 되돌리지 않는다. 그 CLOSED 는 소진이 아니라 완료의 기록이고,
    증빙 실적이 여기에 붙어 있다.
    """
    offer = _own_offer(db, offer_id, user)
    if any(m.status is MatchStatus.DELIVERED for m in offer.matches):
        flash(request, "전달이 완료된 나눔글입니다. 새 나눔글로 올려주세요.")
        return RedirectResponse("/donor/mine", status_code=303)
    if offer.status is not OfferStatus.CLOSED:
        flash(request, "이미 열려 있는 나눔글입니다.")
        return RedirectResponse("/donor/mine", status_code=303)

    offer.status = OfferStatus.OPEN
    db.commit()
    flash(request, f"'{offer.title}' 을(를) 다시 열었습니다.")
    return RedirectResponse("/donor/mine", status_code=303)


@router.post("/credits")
def request_credit(
    request: Request,
    kind: str = Form(...),
    user: User = Depends(donor_dep),
    db: Session = Depends(get_db),
):
    """증빙 신청 접수. 발급 판단은 운영자가 수기로 한다 (자동 발급 금지)."""
    now = datetime.now(timezone.utc)
    period = f"{now.year}년"
    credit_kind = parse_enum(CreditKind, kind, "증빙 종류")

    existing = db.scalar(
        select(Credit).where(
            Credit.donor_id == user.id, Credit.kind == credit_kind, Credit.period_label == period
        )
    )
    if existing is not None:
        flash(request, f"{period} {credit_kind.label}은 이미 신청되어 있습니다.")
        return RedirectResponse("/donor/mine", status_code=303)

    shop = _shop(db, user)
    delivered: list[Match] = []
    if shop:
        offer_ids = [o.id for o in shop.offers]
        if offer_ids:
            delivered = list(
                db.scalars(
                    select(Match).where(
                        Match.offer_id.in_(offer_ids), Match.status == MatchStatus.DELIVERED
                    )
                ).all()
            )

    db.add(
        Credit(
            donor_id=user.id,
            kind=credit_kind,
            period_label=period,
            # 실적 값은 신청 시점 스냅샷일 뿐, 발급 근거는 운영자가 다시 확인한다.
            volunteer_hours=len(delivered) * 2 if credit_kind is CreditKind.VOLUNTEER else None,
        )
    )
    db.commit()
    flash(request, f"{period} {credit_kind.label} 신청이 접수되었습니다. 운영자 검토 후 처리됩니다.")
    return RedirectResponse("/donor/mine", status_code=303)
