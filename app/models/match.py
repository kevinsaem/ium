from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, MatchStatus, TimestampMixin

if TYPE_CHECKING:
    from app.models.case import Case
    from app.models.offer import Offer
    from app.models.user import User


class Match(Base, TimestampMixin):
    """'필요'(Case) ↔ '나눔'(Offer) 연결. 이음의 핵심 트랜잭션.

    승인 단계는 없다. 매니저가 그 후원자를 이미 승인했고, 어느 가정에 보낼지는 그 가정을
    아는 담당 위원의 판단이다 (위원회 결정, 안건 10).
    """

    __tablename__ = "match"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id"), index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offer.id"), index=True)
    proposed_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)

    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, native_enum=False), default=MatchStatus.PROPOSED, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, default=None)

    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivery_note: Mapped[str | None] = mapped_column(Text, default=None)

    case: Mapped["Case"] = relationship(back_populates="matches")
    offer: Mapped["Offer"] = relationship(back_populates="matches")
    proposed_by: Mapped["User"] = relationship(foreign_keys=[proposed_by_id])

    def __repr__(self) -> str:
        return f"<Match {self.id} case={self.case_id} offer={self.offer_id} {self.status.value}>"
