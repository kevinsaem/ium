from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Role, TimestampMixin

if TYPE_CHECKING:
    from app.models.offer import Offer


class User(Base, TimestampMixin):
    """후원자 · 위원 · 운영자 계정.

    대상자(도움받는 분)는 이 테이블에 존재하지 않는다. 앱에 계정이 없는 것이
    이음의 설계 원칙이다.
    """

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 위원·운영자는 이메일로, 후원자는 휴대폰 번호로 로그인한다 (위원회 결정, 안건 07).
    # 후원자에게 이메일을 받지 않기로 했으므로 둘 다 비어 있을 수 있다.
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, default=None)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), index=True)
    dong: Mapped[str] = mapped_column(String(40), default="선부3동")

    # 위원 위촉 관리 (운영자가 승인)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 매니저는 역할이 아니라 위원에게 주는 권한이다 (위원회 결정, 안건 14).
    # "위원 중 한 명이 매니저 역할을 맡으며" — 그래서 Role 을 넷으로 늘리지 않는다.
    is_manager: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # 후원자 승인 (위원회 결정, 안건 10). 거르는 대상은 물건이 아니라 후원자다 —
    # 위원이 발굴해 계정을 만들고, 매니저가 승인해야 그 후원자의 나눔글이 위원에게 보인다.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    # 운영자가 발급하거나 초기화한 임시 비밀번호로는 비밀번호 변경 화면만 쓸 수 있다.
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

    # Shop 은 user 를 두 번 참조한다(owner_id, certified_by_id). 소유 관계만 연결한다.
    shop: Mapped["Shop | None"] = relationship(
        back_populates="owner", uselist=False, foreign_keys="Shop.owner_id"
    )

    @property
    def is_approved(self) -> bool:
        """후원자만 승인이 필요하다. 위원·운영자는 계정 발급 자체가 승인이다."""
        if self.role is not Role.DONOR:
            return True
        return self.approved_at is not None

    def __repr__(self) -> str:
        return f"<User {self.id} {self.role.value} {self.name}>"


class Shop(Base, TimestampMixin):
    """나눔가게. 운영자가 인증 배지를 승인하며, 이것이 '관공서 신뢰 보증'의 실체다."""

    __tablename__ = "shop"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str | None] = mapped_column(String(60), default=None)
    address: Mapped[str | None] = mapped_column(String(255), default=None)
    walk_minutes: Mapped[int | None] = mapped_column(default=None)

    is_certified: Mapped[bool] = mapped_column(Boolean, default=False)
    certified_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    certified_note: Mapped[str | None] = mapped_column(Text, default=None)

    owner: Mapped["User"] = relationship(back_populates="shop", foreign_keys=[owner_id])
    offers: Mapped[list["Offer"]] = relationship(back_populates="shop")

    @property
    def distance_label(self) -> str:
        return f"도보 {self.walk_minutes}분" if self.walk_minutes else "동네"

    def __repr__(self) -> str:
        return f"<Shop {self.id} {self.name}>"
