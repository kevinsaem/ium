from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User

# 위원회 결정(2026-10-17, 안건 13): "본인 기기는 한동안 인증 없이 사용하고 30일 경과 시
# 재인증한다." 가게를 보다 잠깐 들어오는 분에게 매번 숫자를 묻지 않으려는 것이다.
TRUST_DAYS = 30


class TrustedDevice(Base):
    """숫자 없이 들어올 수 있는 기기.

    토큰은 쿠키에만 담고 DB 에는 해시만 둔다 — DB 가 유출돼도 그 값으로 로그인할 수 없다.
    기기를 DB 에 두는 이유는 끊을 수 있어야 해서다. 쿠키만 쓰면 잃어버린 휴대폰을 막을
    방법이 없고, 매니저가 숫자를 초기화해도 그 기기는 계속 들어온다.

    해시는 scrypt 가 아니라 sha256 을 쓴다. 토큰이 이미 256비트 난수라 사전 공격 대상이
    아니고, 요청마다 조회하므로 느린 해시를 쓸 자리가 아니다.
    """

    __tablename__ = "trusted_device"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # 어떤 기기인지 사람이 알아볼 수 있게. 브라우저가 보낸 값이라 신뢰하지 않고 자르기만 한다.
    label: Mapped[str | None] = mapped_column(String(120), default=None)

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<TrustedDevice user={self.user_id} expires={self.expires_at}>"
