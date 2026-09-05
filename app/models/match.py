from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, MatchStatus, TimestampMixin

if TYPE_CHECKING:
    from app.models.case import Case
    from app.models.offer import Offer
    from app.models.user import User


class Match(Base, TimestampMixin):
    """'필요'(Case) ↔ '나눔'(Offer) 연결. 이음의 핵심 트랜잭션."""

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
    approvals: Mapped[list["MatchApproval"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )

    @property
    def approval_count(self) -> int:
        return len(self.approvals)

    def __repr__(self) -> str:
        return f"<Match {self.id} case={self.case_id} offer={self.offer_id} {self.status.value}>"


class MatchApproval(Base):
    """협의체 공동 결정 모드에서의 개별 위원 승인 기록.

    승인 방식이 '위원 단독'으로 결정되면 이 테이블은 승인자 1명만 남는 감사기록이 되고,
    '협의체 공동'이면 정족수 계산의 근거가 된다. 어느 쪽이든 스키마는 그대로다.
    """

    __tablename__ = "match_approval"
    __table_args__ = (UniqueConstraint("match_id", "approver_id", name="uq_match_approver"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match.id"), index=True)
    approver_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    comment: Mapped[str | None] = mapped_column(String(200), default=None)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    match: Mapped["Match"] = relationship(back_populates="approvals")
    approver: Mapped["User"] = relationship()
