"""🔴 식별정보 격리 구역.

이 모듈의 두 테이블만이 대상자를 특정할 수 있는 값을 다룬다.
직접 import 해서 읽지 말고 반드시 app.identity_service 를 거칠 것 —
그래야 접근 로그가 남는다.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.case import Case
    from app.models.user import User


class CaseIdentity(Base, TimestampMixin):
    """대상자 식별정보. 모든 값은 Fernet 암호문으로 저장된다.

    컬럼명에 _enc 를 붙여 둔 건 실수로 평문을 넣는 걸 막기 위한 표식이다.
    쓰기는 identity_service.upsert_identity(), 읽기는 read_identity() 로만.
    """

    __tablename__ = "case_identity"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id"), unique=True, index=True)

    name_enc: Mapped[str | None] = mapped_column(Text, default=None)
    phone_enc: Mapped[str | None] = mapped_column(Text, default=None)
    address_enc: Mapped[str | None] = mapped_column(Text, default=None)
    consult_note_enc: Mapped[str | None] = mapped_column(Text, default=None)

    # 정보주체 동의 근거 (개인정보보호법상 수집 근거를 남긴다)
    consent_obtained_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    consent_note: Mapped[str | None] = mapped_column(Text, default=None)

    case: Mapped["Case"] = relationship(back_populates="identity")

    def __repr__(self) -> str:  # 절대 내용을 노출하지 않는다
        return f"<CaseIdentity case_id={self.case_id} (encrypted)>"


class IdentityAccessLog(Base):
    """식별정보 접근 감사 로그.

    누가·언제·어느 케이스를·왜 열람했는지 남긴다. 감사나 민원이 들어왔을 때
    "식별정보 접근은 이 테이블 하나로 설명된다"가 되게 하는 것이 목적.
    """

    __tablename__ = "identity_access_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("case.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    action: Mapped[str] = mapped_column(String(20))  # read | write
    reason: Mapped[str] = mapped_column(String(200))
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    actor: Mapped["User"] = relationship()
    # 운영자 화면은 case_id 대신 비식별 코드로 보여 준다. CaseIdentity 까지 따라가지 않는다.
    case: Mapped["Case"] = relationship()

    def __repr__(self) -> str:
        return f"<IdentityAccessLog {self.action} case={self.case_id} by={self.actor_id}>"
