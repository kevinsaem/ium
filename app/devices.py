"""기기 기억 — 본인 기기는 30일간 숫자 없이 들어온다.

위원회 결정(2026-10-17, 안건 13): "본인 기기는 한동안 인증 없이 사용하고 30일 경과 시
재인증한다." 가게를 보다 잠깐 들어오는 분에게 매번 숫자 네 자리를 묻지 않으려는 것이다.

토큰은 쿠키에만 담고 DB 에는 sha256 해시만 둔다. 세션 쿠키와 따로 두는 이유는 수명이
다르기 때문이다 — 세션은 브라우저를 닫으면 끝나고, 이 쿠키는 30일 남는다.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TrustedDevice, User
from app.models.device import TRUST_DAYS

COOKIE_NAME = "ium_device"
_TOKEN_BYTES = 32


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(moment: datetime) -> datetime:
    """SQLite 는 tzinfo 없이 돌려준다. 저장은 모두 UTC 이므로 UTC 로 본다."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def remember(db: Session, user: User, label: str | None = None) -> str:
    """이 기기를 기억한다. 쿠키에 담을 토큰을 돌려준다."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    db.add(
        TrustedDevice(
            user_id=user.id,
            token_hash=_hash(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=TRUST_DAYS),
            label=(label or "")[:120] or None,
        )
    )
    db.commit()
    return token


def resolve(db: Session, token: str | None) -> User | None:
    """토큰으로 사람을 찾는다. 만료·해제됐거나 쓸 수 없는 계정이면 None.

    만료된 기기는 찾은 자리에서 지운다. 쌓아 둘 이유가 없고, 남겨 두면 '30일 경과 시
    재인증' 이 기록상으로만 참이 된다.
    """
    if not token:
        return None
    device = db.scalar(select(TrustedDevice).where(TrustedDevice.token_hash == _hash(token)))
    if device is None:
        return None

    if _aware(device.expires_at) <= datetime.now(timezone.utc):
        db.delete(device)
        db.commit()
        return None

    user = device.user
    # 잠긴 계정·위촉 해제된 계정·비밀번호 변경이 걸린 계정은 기기 기억으로 통과시키지 않는다.
    if user is None or not user.is_active or user.locked_at is not None or user.must_change_password:
        return None

    device.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return user


def forget(db: Session, token: str | None) -> None:
    """이 기기만 해제한다 (로그아웃)."""
    if not token:
        return
    device = db.scalar(select(TrustedDevice).where(TrustedDevice.token_hash == _hash(token)))
    if device is not None:
        db.delete(device)
        db.commit()


def forget_all(db: Session, user: User) -> int:
    """그 사람의 모든 기기를 끊는다.

    매니저가 숫자를 초기화할 때 쓴다. 초기화는 보통 '못 들어간다'는 연락을 받고 하는
    일인데, 기기가 살아 있으면 잃어버린 휴대폰이 계속 들어온다.
    """
    devices = list(db.scalars(select(TrustedDevice).where(TrustedDevice.user_id == user.id)).all())
    for device in devices:
        db.delete(device)
    db.commit()
    return len(devices)


def set_cookie(response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=TRUST_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
    )


def clear_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax")
