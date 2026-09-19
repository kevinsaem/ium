"""비밀번호 해시 + 식별정보 암호화.

식별정보(대상자 실명·연락처·주소)는 평문으로 DB에 저장하지 않는다.
컬럼에는 Fernet 암호문만 들어가므로, 실수로 테이블을 조회하거나 백업이
유출되어도 키 없이는 읽히지 않는다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
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


MIN_PASSWORD_LENGTH = 10
# 헷갈리는 글자(0·o, 1·l·i)를 뺐다. 운영자가 소리 내어 불러 주거나 손으로 적어 전하기 때문이다.
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_temp_password() -> str:
    """임시 비밀번호 — 12자를 4자씩 끊어 'k7mq-3xtp-9hva' 처럼 읽기 쉽게."""
    chars = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(12))
    return "-".join(chars[i : i + 4] for i in range(0, 12, 4))


def validate_new_password(password: str, *, email: str) -> str | None:
    """새 비밀번호의 문제를 사람이 읽을 문장으로 돌려준다. 문제가 없으면 None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다."
    lowered = password.strip().lower()
    if lowered in (email.lower(), email.split("@")[0].lower()):
        return "이메일과 같은 비밀번호는 쓸 수 없습니다."
    return None


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
