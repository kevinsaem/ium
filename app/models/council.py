from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User

# 파일럿의 첫 협의체. 1차 구현은 선부3동 하나만 전제했고, 그 데이터를 이 협의체로 옮긴다.
DEFAULT_SLUG = "sunbu3"


class Council(Base, TimestampMixin):
    """동 지역사회보장협의체 — 테넌트 경계.

    안산시의 여러 동이, 나아가 다른 시의 협의체가 같은 시스템 위에서 각자 독립적으로
    활동한다. 선부3동의 나눔글이 선부2동 위원에게 보이지 않고, 지표와 월간보고서도
    동 단위로 집계된다. 식별정보는 말할 것도 없다.

    경계를 '조회할 때 조건을 꼭 넣자'는 약속으로 두지 않는다 — 언젠가 깨진다.
    app/tenancy.py 의 한 통로를 거치게 하고, 빠뜨리면 테스트가 깨지게 고정한다.

    행정구역 기준 데이터는 적재하지 않는다 (2026-10-24 결정: "일단 사용할 동만 수집입력").
    전국 226개 시·군·구를 미리 넣는 대신 쓰는 동만 등록한다. region 을 코드가 아니라
    이름으로 두는 것도 그래서다 — 나중에 행안부 코드로 바꿀 자리는 region_code 다.
    """

    __tablename__ = "council"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 후원자에게 전달하는 전용 주소의 조각. 한 번 배포되면 바꾸기 어려우므로
    # 관리자가 임의로 정하게 두지 않고 슈퍼 관리자가 승인한다.
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)

    region: Mapped[str] = mapped_column(String(60))   # 시·군·구 이름 — 예: "안산시 단원구"
    dong: Mapped[str] = mapped_column(String(40))     # 동 이름 — 예: "선부3동"
    # 행안부 행정구역 코드. 지금은 비어 있고, 기준 데이터를 적재할 때 채운다.
    region_code: Mapped[str | None] = mapped_column(String(20), default=None)

    # 실재하지 않는 협의체·사칭 개설을 막는다. 승인 전에는 아무도 쓸 수 없다.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    # 초대 코드를 연달아 틀리면 이 협의체의 위원 가입 화면이 잠긴다. 계정 잠금과 같은
    # 방식이고(안건 15), 관리자가 화면에서 풀어 준다.
    #
    # 알고 둔 대가가 있다. 지나가는 사람이 아무 코드나 여러 번 넣어 모집을 막을 수 있다.
    # 그래도 두는 이유는 반대쪽이 더 무겁기 때문이다 — 코드를 무한히 넣어 볼 수 있으면
    # 위원 자리가 추측으로 열리고, 위원은 식별정보를 읽는 사람이다. 잠기면 관리자
    # 화면에 뜨고 한 번 눌러 풀 수 있다.
    join_failed_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    join_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    approved_by: Mapped["User | None"] = relationship(foreign_keys=[approved_by_id])
    members: Mapped[list["User"]] = relationship(
        back_populates="council", foreign_keys="User.council_id"
    )

    @property
    def label(self) -> str:
        return f"{self.region} {self.dong}"

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None

    @property
    def join_is_locked(self) -> bool:
        return self.join_locked_at is not None

    def __repr__(self) -> str:
        return f"<Council {self.slug} {self.label}>"
