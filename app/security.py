"""비밀번호 해시 + 식별정보 암호화.

식별정보(대상자 실명·연락처·주소)는 평문으로 DB에 저장하지 않는다.
컬럼에는 Fernet 암호문만 들어가므로, 실수로 테이블을 조회하거나 백업이
유출되어도 키 없이는 읽히지 않는다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import warnings

from cryptography.fernet import Fernet, InvalidToken

from app.config import DEV_IDENTITY_KEY, settings

# --- 비밀번호 -------------------------------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, dk_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    dk = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt_hex), n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return hmac.compare_digest(dk.hex(), dk_hex)


# --- 식별정보 암호화 ------------------------------------------------------


def _load_fernet() -> Fernet:
    key = settings.identity_key.strip()
    if not key:
        if settings.is_production:
            # config 에서 이미 시작을 거부하지만, 이 키만큼은 여기서 한 번 더 막는다.
            raise RuntimeError("IUM_IDENTITY_KEY 없이 운영 모드로 시작할 수 없습니다.")
        warnings.warn(
            "IUM_IDENTITY_KEY 가 비어 있어 개발용 고정키를 사용합니다. "
            "운영 배포 전 반드시 .env 에 새 키를 생성해 넣으세요.",
            RuntimeWarning,
            stacklevel=2,
        )
        key = DEV_IDENTITY_KEY
    return Fernet(key.encode())


_fernet = _load_fernet()


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None or plaintext == "":
        return None
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return "[복호화 실패]"
