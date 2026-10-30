from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CouncilScoped:
    """협의체에 속한 자료임을 나타내는 표식.

    이 믹스인을 붙인 테이블은 협의체 경계 안에서만 조회된다 — 조건을 손으로 쓰지 않고
    app/tenancy.py 의 scoped()·assert_same() 을 거친다. 새 테이블을 만들 때 "다른 동
    위원이 이걸 봐도 되는가" 를 묻고, 아니라면 여기를 붙인다.

    컬럼을 모델마다 따로 쓰지 않고 믹스인으로 둔 건 빠뜨림을 눈에 보이게 하기 위해서다.
    상속 목록에 CouncilScoped 가 있는지만 보면 그 테이블이 경계 안인지 알 수 있다.
    """

    @declared_attr
    def council_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey("council.id"), index=True, nullable=False)

class Role(str, enum.Enum):
    """권한.

    역할이 셋이다. 앞의 둘은 한 동 협의체 안에서 성립하고, 그 바깥을 보는 권한이 SUPER 다.

    관리자(매니저)는 역할이 아니라 위원에게 주는 권한이다 (안건 14, User.is_manager).
    운영자(OFFICE) 역할은 폐기했다 — 관리자 = 매니저 = 협의체당 한 사람으로 정리되면서
    (2026-10-24 결정) 하던 일이 전부 관리자에게 왔고, 역할을 하나 줄이면 개인정보 사전
    승인에서 설명할 것도 하나 줄어든다.

    역할을 늘리기 전에 "그 사람이 위원과 다른 자료를 보는가" 를 먼저 물을 것. 보는 자료가
    같고 할 수 있는 일만 다르다면 역할이 아니라 권한 플래그다.
    """

    DONOR = "donor"    # 후원자 (소상공인·주민)
    MEMBER = "member"  # 협의체 위원 — 관리자도 여기에 속한다
    SUPER = "super"    # 슈퍼 관리자 — 협의체 경계를 넘는다. 식별정보는 여전히 못 본다.

    @property
    def label(self) -> str:
        return {
            "donor": "나눔 후원자",
            "member": "협의체 위원",
            "super": "슈퍼 관리자",
        }[self.value]

    @property
    def tag(self) -> str:
        return {"donor": "후원자", "member": "위원", "super": "슈퍼"}[self.value]

    @property
    def is_scoped(self) -> bool:
        """협의체 안에서만 성립하는 권한인가. SUPER 만 경계를 넘는다."""
        return self is not Role.SUPER


class OfferKind(str, enum.Enum):
    GOODS = "goods"      # 물품
    SERVICE = "service"  # 서비스
    MEAL = "meal"        # 식사
    REPAIR = "repair"    # 수리

    @property
    def label(self) -> str:
        return {"goods": "물품", "service": "서비스", "meal": "식사", "repair": "수리"}[self.value]


class DeliveryMethod(str, enum.Enum):
    MEMBER_PICKUP = "member_pickup"  # 위원이 수령
    BENEFICIARY_VISIT = "visit"      # 대상자 방문
    DELIVERY = "delivery"            # 배달

    @property
    def label(self) -> str:
        return {
            "member_pickup": "위원이 수령",
            "visit": "대상자 방문",
            "delivery": "배달",
        }[self.value]


class OfferStatus(str, enum.Enum):
    """나눔글의 일생.

    나눔글을 건건이 심사하지는 않는다 (위원회 결정, 안건 10·16 — 안건 05 를 뒤집었다).
    거르는 대상은 물건이 아니라 후원자다. 승인된 후원자의 나눔글은 바로 위원에게 보인다.
    """

    OPEN = "open"          # 매칭 가능
    RESERVED = "reserved"  # 매칭 진행 중
    CLOSED = "closed"      # 소진·종료

    @property
    def label(self) -> str:
        return {"open": "나눔 가능", "reserved": "매칭 중", "closed": "종료"}[self.value]


class CaseStatus(str, enum.Enum):
    OPEN = "open"            # 발굴됨, 매칭 대기
    MATCHING = "matching"    # 매칭 진행 중
    RESOLVED = "resolved"    # 전달 완료
    CLOSED = "closed"        # 종결

    @property
    def label(self) -> str:
        return {"open": "매칭 대기", "matching": "매칭 중", "resolved": "전달 완료", "closed": "종결"}[
            self.value
        ]


class MatchStatus(str, enum.Enum):
    PROPOSED = "proposed"    # 위원이 제안, 승인 대기
    APPROVED = "approved"    # 승인 완료
    DELIVERED = "delivered"  # 전달 완료
    CANCELLED = "cancelled"  # 취소

    @property
    def label(self) -> str:
        return {
            "proposed": "승인 대기",
            "approved": "승인 완료",
            "delivered": "전달 완료",
            "cancelled": "취소",
        }[self.value]

