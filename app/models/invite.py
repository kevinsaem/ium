from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CouncilScoped

if TYPE_CHECKING:
    from app.models.council import Council
    from app.models.user import User

# 코드 길이와 글자. 사람이 받아 적고 불러 주는 값이라 혼동되는 글자를 뺀다 —
# 0/O, 1/I/l 이 섞이면 "영이에요 오예요" 를 전화로 묻게 된다.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

# 기본 유효기간과 사용 횟수. 위촉이 한 번에 몇 명씩 이뤄지는 일을 생각해 정했고,
# 발급할 때 바꿀 수 있다.
DEFAULT_DAYS = 14
DEFAULT_MAX_USES = 1
MAX_DAYS = 90
MAX_USES_LIMIT = 30


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class MemberInvite(Base, CouncilScoped):
    """위원 초대 코드.

    위원 계정이 생기는 두 길 중 하나다. 다른 하나는 관리자가 이름과 이메일을 받아 대신
    등록하는 길이고, 둘 다 둔 이유는 위촉 현장이 두 가지이기 때문이다 — 회의 자리에서
    명단을 받아 관리자가 넣는 경우와, 위촉장을 받은 분이 각자 휴대폰으로 가입하는 경우.

    코드로 들어온 계정은 바로 쓸 수 없다. 관리자가 승인해야 열린다. 코드 하나가 단체
    대화방에 잘못 올라가면 그 동의 위원 자리가 열리는 셈인데, 위원은 식별정보를 읽는
    사람이다 — 승인 단계 없이 코드만으로 계정이 서면 그 사고가 곧 유출이 된다.

    그래서 코드에 네 가지가 붙어 있다. 유효기간, 사용 횟수 한도, 무효화, 그리고 승인 대기.
    앞의 셋은 코드가 새는 범위를 줄이고, 마지막 하나는 새어도 막는다.
    """

    __tablename__ = "member_invite"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    max_uses: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_USES)
    used_count: Mapped[int] = mapped_column(Integer, default=0)

    # 무효화는 지우지 않고 표시한다. 누가 언제 발급하고 왜 거뒀는지가 남아야,
    # "그 코드로 들어온 사람" 을 나중에 설명할 수 있다.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)

    note: Mapped[str | None] = mapped_column(Text, default=None)

    council: Mapped["Council"] = relationship()
    created_by: Mapped["User"] = relationship(foreign_keys=[created_by_id])
    revoked_by: Mapped["User | None"] = relationship(foreign_keys=[revoked_by_id])

    @staticmethod
    def deadline(days: int) -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=days)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires < datetime.now(timezone.utc)

    @property
    def is_used_up(self) -> bool:
        return self.used_count >= self.max_uses

    @property
    def is_usable(self) -> bool:
        return not (self.is_revoked or self.is_expired or self.is_used_up)

    @property
    def state_label(self) -> str:
        """화면에 그대로 쓰는 상태. 왜 못 쓰는지를 한 단어로 보여 준다."""
        if self.is_revoked:
            return "무효화됨"
        if self.is_expired:
            return "기간 만료"
        if self.is_used_up:
            return "사용 완료"
        return "사용 가능"

    @property
    def uses_left(self) -> int:
        return max(0, self.max_uses - self.used_count)

    def __repr__(self) -> str:
        return f"<MemberInvite {self.code} {self.state_label}>"
