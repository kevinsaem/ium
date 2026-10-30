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

from app import accounts, identity_service, invites, matching, tenancy
from app.config import settings
from app.db import SessionLocal, engine, upgrade_to_head
from app.icons import KIND_ICON
from app.models import (
    Case,
    DeliveryMethod,
    Offer,
    OfferKind,
    OfferStatus,
    Role,
    Shop,
    ThanksMessage,
    User,
)
from app.security import hash_password

PASSWORD = "ium1234"
# 승인 대기 위원은 실제 가입과 같은 함수(create_pending_member)로 만들므로 비밀번호
# 검증을 거친다. 데모용 ium1234 는 8자라 통과하지 못해 따로 둔다.
PENDING_PASSWORD = "ium-pending-2026"
# 후원자는 휴대폰 번호 + 숫자 4자리로 로그인한다 (위원회 결정, 안건 07).
# 시연용이라 번호와 숫자를 외우기 쉽게 맞춰 두었다.
DONOR_PIN = "2026"

DONORS = [
    # (이름, 휴대폰, 가게, 업종, 도보, 인증여부, 주소, 우편번호)
    # 주소는 지도 링크용 선택 정보다 (안건 13). 시연용 가상 주소다.
    ("김행복", "01010000001", "행복미용실", "미용", 4, True,
     "안산시 단원구 선부동 101-1", "15236"),
    ("박순자", "01010000002", "엄마손칼국수", "분식", 7, True,
     "안산시 단원구 선부동 202-2", "15237"),
    ("강대표", "01010000003", "강마트", "마트", 3, True,
     "안산시 단원구 선부동 303-3", "15238"),
    ("한빛", "01010000004", "한빛철물점", "철물", 9, False, None, None),
    ("최세탁", "01010000005", "푸른세탁소", "세탁", 6, True,
     "안산시 단원구 선부동 505-5", "15239"),
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


def _refuse_in_production() -> None:
    """운영 DB 에는 돌리지 않는다 — 비밀번호가 공개된 가짜 계정이 들어가고, --reset 은 DB 파일을 지운다."""
    if settings.is_production:
        sys.exit(
            "IUM_ENV=production 에서는 시드를 실행하지 않습니다. 비밀번호가 공개된 가짜 계정이 "
            "운영 DB 에 들어가고, --reset 은 DB 파일을 지웁니다."
        )


def seed() -> None:
    _refuse_in_production()
    upgrade_to_head()  # 스키마는 Alembic 이 만든다
    db = SessionLocal()
    try:
        if db.scalar(select(User).limit(1)) is not None:
            print("이미 데이터가 있습니다. 초기화하려면 --reset 을 붙여 실행하세요.")
            return

        # 협의체는 마이그레이션이 넣어 둔다. 시드는 그 협의체 안에 자료를 채운다.
        council = tenancy.default(db)
        cid = council.id

        # 운영자 역할은 폐기했다. 이 계정은 '관리자가 아닌 평범한 위원' 으로 남겨 둔다 —
        # 관리자만 할 수 있는 일을 화면에서 확인할 때 이 계정으로 들어가 보면 된다.
        member3 = User(
            email="member3@ium.test", password_hash=hash_password(PASSWORD),
            name="김복지 위원", role=Role.MEMBER, council_id=cid,
            approved_at=datetime.now(timezone.utc),
        )
        member1 = User(
            email="member1@ium.test", password_hash=hash_password(PASSWORD),
            name="이관희 위원", role=Role.MEMBER, council_id=cid, is_manager=True, appointed_note="2026년 위촉",
            approved_at=datetime.now(timezone.utc),
        )
        member2 = User(
            email="member2@ium.test", password_hash=hash_password(PASSWORD),
            name="정미영 위원", role=Role.MEMBER, council_id=cid, appointed_note="2026년 위촉",
            approved_at=datetime.now(timezone.utc),
        )
        db.add_all([member3, member1, member2])
        db.flush()

        shops: dict[str, Shop] = {}
        for name, phone, shop_name, category, walk, certified, address, postal in DONORS:
            donor = User(
                phone=phone, password_hash=hash_password(DONOR_PIN), name=name, role=Role.DONOR,
                council_id=cid,
                # 시연 데이터는 승인을 마친 상태로 둔다. 승인 대기 화면은 아래에서 한 곳만 남긴다.
                approved_at=datetime.now(timezone.utc),
            )
            db.add(donor)
            db.flush()
            shop = Shop(
                council_id=cid, owner_id=donor.id, name=shop_name, category=category, walk_minutes=walk,
                address=address, postal_code=postal,
                is_certified=certified,
                certified_by_id=member3.id if certified else None,
                certified_note="2026-07 현장 확인" if certified else None,
            )
            db.add(shop)
            db.flush()
            shops[shop_name] = shop

        offers: dict[str, Offer] = {}
        for shop_name, title, kind, icon, qty, delivery in OFFERS:
            offer = Offer(
                council_id=cid, shop_id=shops[shop_name].id, title=title, kind=kind,
                icon=icon or KIND_ICON.get(kind.value, "bag"),
                quantity_note=qty, delivery=delivery,
                # 시연 데이터는 운영팀 승인을 마친 상태로 둔다. 승인 대기 화면은
                # 후원자가 새 나눔글을 올려 보면 바로 확인할 수 있다.
                status=OfferStatus.OPEN,
            )
            db.add(offer)
            db.flush()
            offers[title] = offer

        cases: list[Case] = []
        for code, need, note, size, urgent, identity in CASES:
            case = Case(
                council_id=cid, code=code, need_summary=need, situation_note=note, household_size=size,
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

        # C어르신 ← 이불 세탁: 전달 완료 상태로 만들어 둔다.
        match = matching.propose(db, cases[2], offers["이불 빨래 무료 세탁"], member1, "정기 방문 시 수령")
        matching.mark_delivered(db, match, member1, "8/25 방문 전달 완료")
        db.add(
            ThanksMessage(
                match_id=match.id, written_by_id=member1.id,
                body="덕분에 따뜻한 겨울을 준비할 수 있게 되었습니다",
                created_at=datetime.now(timezone.utc),
            )
        )

        # A가정 ← 도시락: 전달 대기 상태로 남겨 둔다.
        matching.propose(db, cases[0], offers["따뜻한 한끼 도시락 5개"], member1, "화요일 오전 수령 예정")

        # 승인 대기 후원자 한 명을 남겨 둔다 — 매니저 승인 화면을 바로 볼 수 있게 (안건 10).
        waiting = User(
            phone="01010000009", password_hash=hash_password(DONOR_PIN),
            name="신규사장", role=Role.DONOR, council_id=cid,
        )
        db.add(waiting)
        db.flush()
        db.add(Shop(
            council_id=cid, owner_id=waiting.id, name="새봄반찬", category="반찬", walk_minutes=5,
            address="안산시 단원구 선부동 909-9", postal_code="15240",
        ))
        db.commit()

        # 관리자 화면을 바로 볼 수 있게 초대 코드 하나와 승인 대기 위원 한 명을 남긴다.
        invite = invites.create(
            db, member1, days=14, max_uses=3, note="데모용 — 2026년 하반기 위촉"
        )
        pending = accounts.create_pending_member(
            db,
            council_id=cid,
            name="가입대기 위원",
            email="pending@ium.test",
            password=PENDING_PASSWORD,
            note=f"초대 코드 {invite.code}",
        )
        db.commit()

        print(f"시드 완료. 협의체: {council.label} (/{council.slug})")
        print(f"  관리자  member1@ium.test (비밀번호 {PASSWORD}) — 관리 화면 /manage/people")
        print(f"  위원    member2@ium.test / member3@ium.test (비밀번호 {PASSWORD})")
        print(f"  후원자  010-1000-0001 외 4명 (숫자 {DONOR_PIN})")
        print(f"  위원 초대 코드  {invite.code}  →  /c/{council.slug}/join")
        print(f"  승인 대기 위원  {pending.email} (비밀번호 {PENDING_PASSWORD})")
    finally:
        db.close()


if __name__ == "__main__":
    _refuse_in_production()  # --reset 이 파일을 지우기 전에 막아야 한다
    if "--reset" in sys.argv:
        engine.dispose()
        db_file = Path("ium.db")
        if db_file.exists():
            db_file.unlink()
        print("기존 데이터를 삭제했습니다.")
    seed()
