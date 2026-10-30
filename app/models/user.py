from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CouncilScoped, Role, TimestampMixin

if TYPE_CHECKING:
    from app.models.council import Council
    from app.models.offer import Offer


class User(Base, TimestampMixin):
    """후원자 · 위원 · 관리자 계정.

    대상자(도움받는 분)는 이 테이블에 존재하지 않는다. 앱에 계정이 없는 것이
    이음의 설계 원칙이다.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 위원는 이메일로, 후원자는 휴대폰 번호로 로그인한다 (위원회 결정, 안건 07).
    # 후원자에게 이메일을 받지 않기로 했으므로 둘 다 비어 있을 수 있다.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, default=None)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), index=True)
    # 소속 협의체. 슈퍼 관리자는 경계 밖이라 비어 있다.
    council_id: Mapped[int | None] = mapped_column(
        ForeignKey("council.id"), index=True, default=None
    )
    dong: Mapped[str] = mapped_column(String(40), default="선부3동")

    # 위원 위촉 관리 (관리자가 승인)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 매니저는 역할이 아니라 위원에게 주는 권한이다 (위원회 결정, 안건 14).
    # "위원 중 한 명이 매니저 역할을 맡으며" — 그래서 Role 을 넷으로 늘리지 않는다.
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # 후원자 승인 (위원회 결정, 안건 10). 거르는 대상은 물건이 아니라 후원자다 —
    # 위원이 발굴해 계정을 만들고, 매니저가 승인해야 그 후원자의 나눔글이 위원에게 보인다.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    # 관리자가 발급하거나 초기화한 임시 비밀번호로는 비밀번호 변경 화면만 쓸 수 있다.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    appointed_note: Mapped[str | None] = mapped_column(Text, default=None)

    # 숫자 4자리는 1만 가지뿐이라 하나씩 넣어 보는 시도에 약하다. 연속 실패를 세서 잠근다.
    #
    # 잠금은 시간이 지나 저절로 풀리지 않는다 — 매니저가 해제한다 (위원회 결정, 안건 15).
    # 10분 뒤 자동 해제로 두면 매니저 화면에는 아무것도 뜨지 않아, '매니저가 해제한다'는
    # 결정이 사실상 없는 기능이 된다. 대신 로그인 화면에 운영팀 연락처를 띄운다.
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    approved_by: Mapped["User | None"] = relationship(
        foreign_keys=[approved_by_id], remote_side="User.id"
    )
    council: Mapped["Council | None"] = relationship(
        back_populates="members", foreign_keys=[council_id]
    )

    # Shop 은 user 를 두 번 참조한다(owner_id, certified_by_id). 소유 관계만 연결한다.
    shop: Mapped["Shop | None"] = relationship(
        back_populates="owner", uselist=False, foreign_keys="Shop.owner_id"
    )

    @property
    def is_approved(self) -> bool:
        """승인이 필요한 계정인가, 받았는가.

        후원자는 매니저가 승인한다 (안건 10). 위원도 승인이 필요하다 — 초대 코드로
        들어오는 길이 생겼기 때문이다. 코드가 단체 대화방에 잘못 올라가면 그 동의 위원
        자리가 열리는 셈이고, 위원은 식별정보를 읽는 사람이다.

        관리자가 이름과 이메일을 받아 직접 발급한 계정은 발급 자체가 승인이므로 그때
        approved_at 을 찍는다. 그래서 여기서 '어떻게 들어왔는지' 를 따로 묻지 않는다 —
        승인한 사람이 있으면 승인된 것이다.

        슈퍼 관리자는 서버 명령으로만 생기므로 승인할 상위가 없다.
        """
        if self.role is Role.SUPER:
            return True
        return self.approved_at is not None

    def __repr__(self) -> str:
        return f"<User {self.id} {self.role.value} {self.name}>"


class Shop(Base, CouncilScoped, TimestampMixin):
    """나눔가게. 관리자가 인증 배지를 승인하며, 이것이 '관공서 신뢰 보증'의 실체다."""

    __tablename__ = "shop"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(60), default=None)
    address: Mapped[str | None] = mapped_column(String(255), default=None)
    # 선택 정보 (위원회 결정, 안건 13). 주소는 지도에 띄워 "담당 위원 외 다른 봉사위원도
    # 가게를 쉽게 찾아갈 수 있게" 하는 용도다.
    postal_code: Mapped[str | None] = mapped_column(String(10), default=None)
    walk_minutes: Mapped[int | None] = mapped_column(default=None)

    is_certified: Mapped[bool] = mapped_column(Boolean, default=False)
    certified_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    certified_note: Mapped[str | None] = mapped_column(Text, default=None)

    owner: Mapped["User"] = relationship(back_populates="shop", foreign_keys=[owner_id])
    offers: Mapped[list["Offer"]] = relationship(back_populates="shop")

    @property
    def map_url(self) -> str | None:
        """주소를 지도에서 찾는 링크.

        지도 API 키 없이 공개 검색 주소를 쓴다. 휴대폰에서는 지도 앱이 열리고 PC 에서는
        웹 지도가 열린다. 파일럿에 지도 API 계약을 붙일 이유가 없다.
        """
        if not self.address:
            return None
        from urllib.parse import quote

        return f"https://map.kakao.com/?q={quote(self.address)}"

    @property
    def distance_label(self) -> str:
        return f"도보 {self.walk_minutes}분" if self.walk_minutes else "동네"

    def __repr__(self) -> str:
        return f"<Shop {self.id} {self.name}>"
