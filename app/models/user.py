from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, false
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
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), index=True)
    dong: Mapped[str] = mapped_column(String(40), default="선부3동")

    # 위원 위촉 관리 (운영자가 승인)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 운영자가 발급하거나 초기화한 임시 비밀번호로는 비밀번호 변경 화면만 쓸 수 있다.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    appointed_note: Mapped[str | None] = mapped_column(Text, default=None)

    # Shop 은 user 를 두 번 참조한다(owner_id, certified_by_id). 소유 관계만 연결한다.
    shop: Mapped["Shop | None"] = relationship(
        back_populates="owner", uselist=False, foreign_keys="Shop.owner_id"
    )

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
