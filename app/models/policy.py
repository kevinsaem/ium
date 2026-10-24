from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User

# 보관 기간은 두 번 정해졌다.
#
#   1차(안건 01): 종결 후 3개월까지 보관하고 파기.
#   2차(안건 09): "식별정보를 전부 파기하지 않는다. 후원받는 분의 동의를 받아 누가 언제
#                무엇을 받았는지 기록을 3년간 보관한다."
#
# 그래서 36개월이다. 동의가 보관의 근거이므로 동의 없이는 저장하지 않는다
# (app/identity_service.py 의 upsert_identity).
#
# "하드코딩으로 하지 말고" 운영자가 화면에서 바꿀 수 있어야 한다는 1차 결정은 그대로 둔다 —
# 행정복지센터 협의에서 기간이 달라질 수 있다.
DEFAULT_RETENTION_MONTHS = 36
MIN_RETENTION_MONTHS = 1
MAX_RETENTION_MONTHS = 60

# 위원회 결정(안건 04): 파일럿 기간은 1개월. 시작일은 "완성되고 나서 해야 되는 거니까"
# 지금 정하지 않고 운영자가 화면에서 넣는다.
DEFAULT_PILOT_MONTHS = 1


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

    # 파일럿 기간. 시작일이 비어 있으면 지표를 누적으로 보여 준다.
    pilot_start: Mapped[date | None] = mapped_column(Date, default=None)
    pilot_months: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_PILOT_MONTHS, server_default=text(str(DEFAULT_PILOT_MONTHS))
    )

    # 로그인 화면에 띄우는 운영팀 연락처 (위원회 결정, 안건 15).
    # 잠긴 분이 어디로 연락할지 모르는 것이 잠금 자체보다 불편하다.
    team_contact: Mapped[str | None] = mapped_column(String(120), default=None)

    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    updated_by: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:
        return f"<Policy retention={self.identity_retention_months}months>"
