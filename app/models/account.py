from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class AccountEvent(Base):
    """계정 기록 — 발급, 비밀번호 초기화·변경, 위촉 해제·복구.

    운영자는 식별정보를 볼 수 없지만 위원 비밀번호는 초기화할 수 있다. 초기화한 임시
    비밀번호로 위원 계정에 들어가면 그 경계가 무너진다. 막을 수는 없으니 조용히 일어나지
    않게 한다 — 누가·언제·누구의 비밀번호를 초기화했는지 여기에 남는다.
    """

    __tablename__ = "account_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)  # 대상 계정
    # 서버 명령(python -m app.create_office)으로 생긴 계정은 행위자가 없다.
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), index=True, default=None)
    action: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id])

    def __repr__(self) -> str:
        return f"<AccountEvent {self.action} user={self.user_id} by={self.actor_id}>"
