"""개발용 시드 데이터.

프로토타입의 더미데이터를 그대로 옮겨 담아, 로그인 직후 화면이 프로토타입과
같은 모습으로 뜨게 한다. 대상자 식별정보는 전부 가상의 값이다.

    python seed.py          # 기존 DB 유지, 비어 있을 때만 생성
    python seed.py --reset  # DB 삭제 후 재생성
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app import identity_service, matching
from app.db import SessionLocal, engine, upgrade_to_head
from app.icons import KIND_ICON
from app.models import (
    Case,
    DeliveryMethod,
    Offer,
    OfferKind,
    Role,
    Shop,
    ThanksMessage,
    User,
)
from app.security import hash_password

PASSWORD = "ium1234"

DONORS = [
    # (이름, 이메일, 가게, 업종, 도보, 인증여부)
    ("김행복", "happy@ium.test", "행복미용실", "미용", 4, True),
    ("박순자", "mom@ium.test", "엄마손칼국수", "분식", 7, True),
    ("강대표", "kangmart@ium.test", "강마트", "마트", 3, True),
    ("한빛", "hanbit@ium.test", "한빛철물점", "철물", 9, False),
    ("최세탁", "blue@ium.test", "푸른세탁소", "세탁", 6, True),
]

OFFERS = [
    ("행복미용실", "무료 커트 3장 나눔", OfferKind.SERVICE, "scissors", "매달 3장", DeliveryMethod.BENEFICIARY_VISIT),
    ("엄마손칼국수", "따뜻한 한끼 도시락 5개", OfferKind.MEAL, "meal", "매주 화요일 5개", DeliveryMethod.MEMBER_PICKUP),
    ("강마트", "쌀 10kg · 2포", OfferKind.GOODS, "bag", "2포 (재고 소진 시까지)", DeliveryMethod.DELIVERY),
    ("한빛철물점", "도어록·수도 수리 지원", OfferKind.REPAIR, "fix", "월 2건", DeliveryMethod.BENEFICIARY_VISIT),
    ("푸른세탁소", "이불 빨래 무료 세탁", OfferKind.SERVICE, "basket", "월 4건", DeliveryMethod.MEMBER_PICKUP),
]

# (코드, 필요, 상황메모, 가구원, 긴급) + 가상의 식별정보
CASES = [
    ("선부3동 A가정", "식료품 시급", "가장 실직 · 4인 가족 · 상담 후 발굴", 4, True,
     {"name": "홍길동", "phone": "010-0000-0001", "address": "안산시 단원구 선부3동 (가상)",
      "consult_note": "8/20 대면 상담. 실직 3개월차, 자녀 2명 급식 지원 필요."}),
    ("선부3동 B가정", "집수리 필요", "교통사고 후 거동 불편", 2, False,
     {"name": "김철수", "phone": "010-0000-0002", "address": "안산시 단원구 선부3동 (가상)",
      "consult_note": "8/22 방문. 현관 도어록 고장, 세대주 거동 불편."}),
    ("선부3동 C어르신", "겨울 이불", "독거 어르신 · 정기 방문 대상", 1, False,
     {"name": "이영희", "phone": "010-0000-0003", "address": "안산시 단원구 선부3동 (가상)",
      "consult_note": "정기 방문 대상. 난방 취약, 겨울 대비 침구 필요."}),
]


def seed() -> None:
    upgrade_to_head()  # 스키마는 Alembic 이 만든다
    db = SessionLocal()
    try:
        if db.scalar(select(User).limit(1)) is not None:
            print("이미 데이터가 있습니다. 초기화하려면 --reset 을 붙여 실행하세요.")
            return

        office = User(
            email="office@ium.test", password_hash=hash_password(PASSWORD),
            name="협의체 운영자", role=Role.OFFICE,
        )
        member1 = User(
            email="member1@ium.test", password_hash=hash_password(PASSWORD),
            name="이관희 위원", role=Role.MEMBER, appointed_note="2026년 위촉",
        )
        member2 = User(
            email="member2@ium.test", password_hash=hash_password(PASSWORD),
            name="정미영 위원", role=Role.MEMBER, appointed_note="2026년 위촉",
        )
        db.add_all([office, member1, member2])
        db.flush()

        shops: dict[str, Shop] = {}
        for name, email, shop_name, category, walk, certified in DONORS:
            donor = User(
                email=email, password_hash=hash_password(PASSWORD), name=name, role=Role.DONOR
            )
            db.add(donor)
            db.flush()
            shop = Shop(
                owner_id=donor.id, name=shop_name, category=category, walk_minutes=walk,
                is_certified=certified,
                certified_by_id=office.id if certified else None,
                certified_note="2026-07 현장 확인" if certified else None,
            )
            db.add(shop)
            db.flush()
            shops[shop_name] = shop

        offers: dict[str, Offer] = {}
        for shop_name, title, kind, icon, qty, delivery in OFFERS:
            offer = Offer(
                shop_id=shops[shop_name].id, title=title, kind=kind,
                icon=icon or KIND_ICON.get(kind.value, "bag"),
                quantity_note=qty, delivery=delivery,
            )
            db.add(offer)
            db.flush()
            offers[title] = offer

        cases: list[Case] = []
        for code, need, note, size, urgent, identity in CASES:
            case = Case(
                code=code, need_summary=need, situation_note=note, household_size=size,
                is_urgent=urgent, member_id=member1.id,
            )
            db.add(case)
            db.flush()
            identity_service.upsert_identity(
                db, case, member1,
                name=identity["name"], phone=identity["phone"], address=identity["address"],
                consult_note=identity["consult_note"],
                consent_note="상담 시 구두 동의 (개발용 가상 데이터)",
                consent_given=True,
            )
            cases.append(case)
        db.commit()

        # C어르신 ← 이불 세탁: 승인까지 마치고 전달 완료 상태로 만들어 둔다.
        match = matching.propose(db, cases[2], offers["이불 빨래 무료 세탁"], member1, "정기 방문 시 수령")
        matching.approve(db, match, member2, comment="협의체 공동 결정")
        matching.mark_delivered(db, match, member1, "8/25 방문 전달 완료")
        db.add(
            ThanksMessage(
                match_id=match.id, written_by_id=member1.id,
                body="덕분에 따뜻한 겨울을 준비할 수 있게 되었습니다",
                created_at=datetime.now(timezone.utc),
            )
        )

        # A가정 ← 도시락: 승인 대기 상태로 남겨 둔다 (승인 흐름 확인용).
        matching.propose(db, cases[0], offers["따뜻한 한끼 도시락 5개"], member1, "화요일 오전 수령 예정")
        db.commit()

        print("시드 완료. 비밀번호는 모두 'ium1234' 입니다.")
        print("  운영자  office@ium.test")
        print("  위원    member1@ium.test / member2@ium.test")
        print("  후원자  happy@ium.test 외 4명")
    finally:
        db.close()


if __name__ == "__main__":
    if "--reset" in sys.argv:
        engine.dispose()
        db_file = Path("ium.db")
        if db_file.exists():
            db_file.unlink()
        print("기존 데이터를 삭제했습니다.")
    seed()
