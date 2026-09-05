from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CaseStatus, TimestampMixin

if TYPE_CHECKING:
    from app.models.identity import CaseIdentity
    from app.models.match import Match
    from app.models.user import User


class Case(Base, TimestampMixin):
    """위원이 발굴한 '필요'.

    ⚠️ 이 테이블에는 식별정보를 절대 넣지 않는다.
    실명·연락처·주소는 case_identity 테이블에 암호화되어 따로 저장되며,
    앱의 나머지 기능(매칭·통계·보고서)은 전부 이 비식별 레코드만으로 동작한다.

    새 컬럼을 추가할 때 "이 값으로 특정 개인을 알아볼 수 있는가?"를 먼저 물을 것.
    그렇다면 여기가 아니라 CaseIdentity 로 가야 한다.
    """

    __tablename__ = "case"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 비식별 코드 — 화면에 노출되는 유일한 호칭. 예: "선부3동 A가정"
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)

    need_summary: Mapped[str] = mapped_column(String(160))          # "식료품 시급"
    situation_note: Mapped[str | None] = mapped_column(Text)        # "가장 실직 · 4인 가족"
    household_size: Mapped[int | None] = mapped_column(default=None)
    is_urgent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, native_enum=False), default=CaseStatus.OPEN, index=True
    )

    # 공적지원 연계 체크 — 단발 나눔으로 끝내지 않고 공적 복지로 넘기는 트리거
    public_support_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    public_support_note: Mapped[str | None] = mapped_column(Text, default=None)

    # 발굴한 위원 (담당자)
    member_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    member: Mapped["User"] = relationship()

    identity: Mapped["CaseIdentity | None"] = relationship(
        back_populates="case", uselist=False, cascade="all, delete-orphan"
    )
    matches: Mapped[list["Match"]] = relationship(back_populates="case")

    @property
    def has_identity(self) -> bool:
        """식별정보가 등록되어 있는지 — 내용은 노출하지 않고 존재 여부만."""
        return self.identity is not None

    def __repr__(self) -> str:
        return f"<Case {self.id} {self.code}>"
