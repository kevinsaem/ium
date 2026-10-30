"""식별정보 접근의 유일한 통로.

CaseIdentity 를 직접 쿼리해서 복호화하는 코드를 다른 곳에 쓰지 말 것.
이 모듈을 거쳐야만 IdentityAccessLog 가 남는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Case, CaseIdentity, IdentityAccessLog, Role, User
from app import permissions
from app.permissions import can
from app.security import decrypt, encrypt


def _authorize(actor: User, case: Case, action: str) -> None:
    """식별정보에 닿을 수 있는 사람은 그 가정의 담당 위원뿐이다.

    권한 표(app/permissions.py)에서 이 자리의 행위자는 '위원' 이 아니라 '담당 위원'
    (CASE_MEMBER)이다. 담당인지는 케이스가 정해져야 알 수 있으므로 표가 대신 묻지 못하고,
    여기서 확인한다 — 표와 코드가 갈라지지 않게 두 줄을 붙여 둔다.
    """
    if actor.role is not Role.MEMBER or not can(permissions.CASE_MEMBER, "case_identity", action):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="식별정보는 협의체 위원만 접근할 수 있습니다.",
        )
    # 위원이라도 자기가 담당한 케이스만. 동네 전체 위원이 모든 가정을 열람하는 걸 막는다.
    # 관리자도 예외가 아니다 — 관리자는 위원 중 한 명이고, 남의 가정은 못 읽는다.
    if case.member_id != actor.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="담당 위원이 아닌 케이스의 식별정보는 열람할 수 없습니다.",
        )


def _log(db: Session, case: Case, actor: User, action: str, reason: str) -> None:
    db.add(
        IdentityAccessLog(
            case_id=case.id,
            actor_id=actor.id,
            action=action,
            reason=reason[:200],
            # 누가 읽었느냐가 아니라 무엇을 읽었느냐로 소속을 정한다. 슈퍼 관리자가
            # 읽어도 그 기록은 그 동 협의체의 기록으로 남아야 감사가 끊기지 않는다.
            council_id=case.council_id,
        )
    )


def log_handover(db: Session, case: Case, actor: User, from_member: User, to_member: User) -> None:
    """담당 위원 변경을 열람 기록과 같은 자리에 남긴다.

    식별정보를 직접 읽는 행위는 아니지만 '이제 누가 읽을 수 있는가'가 바뀌는 사건이다.
    열람 기록만 남기고 배정 변경을 남기지 않으면 감사가 중간에 끊긴다.
    """
    _log(
        db,
        case,
        actor,
        "handover",
        f"담당 위원 변경: {from_member.name} → {to_member.name}",
    )


def read_identity(db: Session, case: Case, actor: User, reason: str) -> dict[str, str | None]:
    """복호화된 식별정보를 반환하고 열람 사실을 기록한다.

    reason 은 필수다. "왜 열었는지" 없이 열 수 있으면 로그가 의미를 잃는다.
    """
    if not reason or not reason.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="열람 사유를 입력해야 합니다.")

    _authorize(actor, case, "read")
    _log(db, case, actor, "read", reason)
    db.commit()

    identity = case.identity
    if identity is None:
        return {"name": None, "phone": None, "address": None, "consult_note": None}

    return {
        "name": decrypt(identity.name_enc),
        "phone": decrypt(identity.phone_enc),
        "address": decrypt(identity.address_enc),
        "consult_note": decrypt(identity.consult_note_enc),
        "consent_obtained_at": identity.consent_obtained_at,
        "consent_note": identity.consent_note,
    }


def upsert_identity(
    db: Session,
    case: Case,
    actor: User,
    *,
    name: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    consult_note: str | None = None,
    consent_note: str | None = None,
    consent_given: bool = False,
) -> CaseIdentity:
    """식별정보 등록·수정.

    동의가 보관의 근거다 (위원회 결정, 안건 09 — "후원받는 분의 동의를 받아 ... 3년간
    보관한다"). 동의 없이 저장할 수 있게 두면 근거 없는 보관이 생긴다. 그래서 처음 저장할
    때 동의 표시를 요구한다 — 이미 동의가 기록된 케이스는 수정할 때 다시 묻지 않는다.
    """
    _authorize(actor, case, "write")

    identity = case.identity
    if identity is None:
        if not consent_given:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=(
                    "정보주체의 수집·이용 동의를 받아야 저장할 수 있습니다. "
                    "동의 확인란에 체크하고 근거를 메모에 남겨 주세요."
                ),
            )
        identity = CaseIdentity(case_id=case.id)
        db.add(identity)
        case.identity = identity

    identity.name_enc = encrypt(name)
    identity.phone_enc = encrypt(phone)
    identity.address_enc = encrypt(address)
    identity.consult_note_enc = encrypt(consult_note)
    identity.consent_note = consent_note
    if consent_given and identity.consent_obtained_at is None:
        identity.consent_obtained_at = datetime.now(timezone.utc)

    _log(db, case, actor, "write", "식별정보 등록/수정")
    db.commit()
    db.refresh(identity)
    return identity


def _destroy(db: Session, case: Case, actor: User, reason: str) -> None:
    if case.identity is not None:
        db.delete(case.identity)
        case.identity = None
    _log(db, case, actor, "purge", reason)
    db.commit()


def purge_identity(db: Session, case: Case, actor: User, reason: str) -> None:
    """담당 위원이 누르는 파기. 비식별 Case 레코드와 통계는 그대로 남는다."""
    _authorize(actor, case, "write")
    _destroy(db, case, actor, reason)


def purge_expired_identity(db: Session, case: Case, actor: User, reason: str) -> None:
    """보관 기한이 지난 식별정보를 관리자가 일괄 파기한다 (위원회 결정, 안건 01).

    열람 권한과는 다른 권한이다. 이 함수는 복호화하지 않는다 — 내용을 보지 않고 지우기만
    한다. 권한 표의 identity_retention 이 그 경계다.

    운영자 역할을 폐기하면서 집행 주체가 관리자로 왔다 (2026-10-24 결정). 관리자도 위원이라
    자기 담당 케이스는 읽을 수 있지만, 그건 담당 위원으로서의 권한이고 이 함수와는 다른
    길이다. 여기서는 어느 케이스든 내용을 열지 않고 지운다.
    """
    if not can(actor, "identity_retention", "write"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="보관 기한 집행은 협의체 관리자만 할 수 있습니다.",
        )
    _destroy(db, case, actor, reason)
