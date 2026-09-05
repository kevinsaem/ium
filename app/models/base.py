from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Role(str, enum.Enum):
    DONOR = "donor"    # 후원자 (소상공인·주민)
    MEMBER = "member"  # 협의체 위원
    OFFICE = "office"  # 협의체 운영자

    @property
    def label(self) -> str:
        return {"donor": "나눔 후원자", "member": "협의체 위원", "office": "협의체 운영자"}[self.value]

    @property
    def tag(self) -> str:
        return {"donor": "후원자", "member": "위원", "office": "운영자"}[self.value]


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


class CreditKind(str, enum.Enum):
    VOLUNTEER = "volunteer"  # 자원봉사 실적 (1365 연계)
    DONATION = "donation"    # 기부금 영수증 — 발급요건 확인 전까지 신청만 접수

    @property
    def label(self) -> str:
        return {"volunteer": "자원봉사 실적 인증", "donation": "기부금 영수증"}[self.value]


class CreditStatus(str, enum.Enum):
    REQUESTED = "requested"  # 신청 접수
    ISSUED = "issued"        # 발급 완료
    REJECTED = "rejected"    # 요건 미충족

    @property
    def label(self) -> str:
        return {"requested": "신청 접수", "issued": "발급 완료", "rejected": "요건 미충족"}[self.value]
