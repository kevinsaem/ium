from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class DonorNote(Base):
    """후원자별 메모 — 위원이 쌓아 올린다 (위원회 결정, 안건 13).

    "후원자별 메모를 누적 추가할 수 있으며 각 메모엔 날짜, 시간, 작성자, 내용이 함께
    기록된다." 고쳐 쓰는 메모가 아니라 쌓이는 기록이다. 그래서 수정·삭제를 두지 않았다 —
    "지난번에 뭐라고 했더라" 를 알려면 고쳐 쓴 흔적이 아니라 그때 적은 말이 남아야 한다.

    대상자 정보가 아니라 가게 정보다. 담당 위원만 보는 식별정보와 달리, 위원들이 함께 본다 —
    "다른 봉사위원도 가게를 쉽게 찾아갈 수 있게" 하자는 같은 결정의 연장이다.
    """

    __tablename__ = "donor_note"

    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    donor: Mapped["User"] = relationship(foreign_keys=[donor_id])
    author: Mapped["User"] = relationship(foreign_keys=[author_id])

    def __repr__(self) -> str:
        return f"<DonorNote donor={self.donor_id} by={self.author_id}>"
