"""식별정보 접근의 유일한 통로.

CaseIdentity 를 직접 쿼리해서 복호화하는 코드를 다른 곳에 쓰지 말 것.
이 모듈을 거쳐야만 IdentityAccessLog 가 남는다.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Case, CaseIdentity, IdentityAccessLog, Role, User
from app.permissions import can
from app.security import decrypt, encrypt


def _authorize(actor: User, case: Case, action: str) -> None:
    if not can(actor.role, "case_identity", action):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="식별정보는 협의체 위원만 접근할 수 있습니다.",
        )
    # 위원이라도 자기가 담당한 케이스만. 동네 전체 위원이 모든 가정을 열람하는 걸 막는다.
    if actor.role is Role.MEMBER and case.member_id != actor.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="담당 위원이 아닌 케이스의 식별정보는 열람할 수 없습니다.",
        )


def _log(db: Session, case: Case, actor: User, action: str, reason: str) -> None:
    db.add(
        IdentityAccessLog(
            case_id=case.id, actor_id=actor.id, action=action, reason=reason[:200]
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
    _authorize(actor, case, "write")

    identity = case.identity
    if identity is None:
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


def purge_identity(db: Session, case: Case, actor: User, reason: str) -> None:
    """케이스 종결 후 식별정보 파기. 비식별 Case 레코드와 통계는 그대로 남는다."""
    _authorize(actor, case, "write")
    if case.identity is not None:
        db.delete(case.identity)
        case.identity = None
    _log(db, case, actor, "write", f"식별정보 파기: {reason}")
    db.commit()
