from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.match import Match


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
