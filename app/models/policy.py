from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User

# 위원회 결정(2026-09-19, 안건 01): 종결 후 3개월까지 보관하고 그 뒤 파기.
# "하드코딩으로 하지 말고" 운영자가 화면에서 바꿀 수 있어야 한다.
DEFAULT_RETENTION_MONTHS = 3
MIN_RETENTION_MONTHS = 1
MAX_RETENTION_MONTHS = 60


class Policy(Base):
    """운영자가 화면에서 바꾸는 운영 정책. 한 행만 쓴다.

    app/config.py 의 settings 와 역할이 다르다. 그쪽은 배포할 때 정하는 값(키·DB 주소)이라
    운영자가 손댈 수 없고, 이쪽은 협의체가 운영하면서 바꾸는 값이다.

    항목을 추가할 때마다 마이그레이션이 필요하지만, 그래도 컬럼으로 둔다. 키-값 표로 두면
    "이 설정이 몇 개월인지" 를 문자열로 주고받다가 잘못된 값이 조용히 섞인다.
    """

    __tablename__ = "policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # 케이스 종결 후 식별정보를 며칠까지 보관할지 — 개월 단위
    identity_retention_months: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_RETENTION_MONTHS, server_default=text(str(DEFAULT_RETENTION_MONTHS))
    )

    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    updated_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Policy retention={self.identity_retention_months}months>"
