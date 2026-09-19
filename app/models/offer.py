from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, DeliveryMethod, OfferKind, OfferStatus, TimestampMixin

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.user import Shop, User


class Offer(Base, TimestampMixin):
    """후원자가 '내놓기(Push)'로 올린 나눔글.

    받는 분이 누구인지는 이 테이블 어디에도 없다. Offer 는 Match 를 통해
    비식별 Case 코드에만 연결된다.
    """

    __tablename__ = "offer"

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shop.id"), index=True)

    title: Mapped[str] = mapped_column(String(160))
    kind: Mapped[OfferKind] = mapped_column(Enum(OfferKind, native_enum=False), index=True)
    icon: Mapped[str] = mapped_column(String(24), default="bag")
    quantity_note: Mapped[str | None] = mapped_column(String(160), default=None)
    delivery: Mapped[DeliveryMethod] = mapped_column(
        Enum(DeliveryMethod, native_enum=False), default=DeliveryMethod.MEMBER_PICKUP
    )
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[OfferStatus] = mapped_column(
        Enum(OfferStatus, native_enum=False), default=OfferStatus.PENDING, index=True
    )

    # 운영팀의 노출 심사 기록. 거절 사유는 후원자에게 그대로 보인다.
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    review_note: Mapped[str | None] = mapped_column(Text, default=None)

    shop: Mapped["Shop"] = relationship(back_populates="offers")
    matches: Mapped[list["Match"]] = relationship(back_populates="offer")
    reviewed_by: Mapped["User | None"] = relationship(foreign_keys=[reviewed_by_id])

    def __repr__(self) -> str:
        return f"<Offer {self.id} {self.title}>"
