from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreditKind, CreditStatus, TimestampMixin

if TYPE_CHECKING:
    from app.models.match import Match
    from app.models.user import User


class Credit(Base, TimestampMixin):
    """후원자에게 돌아가는 공식 증빙.

    ⚠️ 기부금 영수증은 법정기부금단체만 발급할 수 있다. 협의체가 발급 주체가 될 수
    있는지 확인되기 전까지 DONATION 은 '신청 접수'까지만 처리하고 운영자가 수기로
    판단한다. 자동 발급 로직을 여기에 넣지 말 것.
    """

    __tablename__ = "credit"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    kind: Mapped[CreditKind] = mapped_column(Enum(CreditKind, native_enum=False))
    status: Mapped[CreditStatus] = mapped_column(
        Enum(CreditStatus, native_enum=False), default=CreditStatus.REQUESTED, index=True
    )

    period_label: Mapped[str] = mapped_column(String(40))          # "2026년" / "2026-08"
    volunteer_hours: Mapped[int | None] = mapped_column(default=None)
    amount_krw: Mapped[int | None] = mapped_column(default=None)   # 환산액
    issued_note: Mapped[str | None] = mapped_column(Text, default=None)
    processed_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)

    donor: Mapped["User"] = relationship(foreign_keys=[donor_id])


class ThanksMessage(Base):
    """익명 감사 메시지.

    위원이 대상자의 말을 옮겨 적되 대상자를 특정할 수 있는 표현은 넣지 않는다.
    후원자에게는 "선부3동 한 가정 · 위원 전달"로만 보인다.
    """

    __tablename__ = "thanks_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("match.id"), index=True)
    written_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    match: Mapped["Match"] = relationship()
