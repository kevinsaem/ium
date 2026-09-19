"""애플리케이션 설정.

MATCH_APPROVAL_MODE 는 슬라이드 6 안건 ⑤(매칭 승인 프로세스)가 아직 미정이라
코드가 아니라 설정으로 바꿀 수 있게 빼 두었다. 위원회 결정이 나면 .env 한 줄만 고치면 된다.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """.env 를 읽어 os.environ 에 채운다 (이미 설정된 값은 덮어쓰지 않는다).

    실제 환경변수가 항상 이기므로, 테스트나 배포 환경에서 .env 가 끼어들지 않는다.
    의존성을 하나 줄이려고 직접 구현했다 — 형식은 KEY=value, # 는 주석.
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# 테스트에서 승인 모드를 갈아끼울 수 있게 frozen 은 쓰지 않는다.
@dataclass
class Settings:
    secret_key: str = _env("IUM_SECRET_KEY", "dev-only-insecure-session-secret")
    identity_key: str = _env("IUM_IDENTITY_KEY", "")
    database_url: str = _env("IUM_DATABASE_URL", "sqlite:///./ium.db")

    # 나눔글을 위원에게 노출하기 전 운영팀이 승인할지 (위원회 결정, 안건 05).
    # "향후에 좀 번거로우면 승인 단계를 뺄 수도 있지 않을까" — 그래서 설정으로 뺐다.
    offer_approval: bool = _env("IUM_OFFER_APPROVAL", "on").strip().lower() not in {
        "off", "false", "0", "no"
    }

    # 파일럿 대상 동
    dong: str = _env("IUM_DONG", "선부3동")

    # development | production — production 에서는 개발용 값으로 시작하지 않는다.
    env: str = _env("IUM_ENV", "development")

    @property
    def is_production(self) -> bool:
        return self.env.strip().lower() == "production"


# 소스에 적혀 있는 값들. 저장소가 공개되어 있으므로 이 값들은 비밀이 아니다.
DEV_SECRET_KEYS = {"dev-only-insecure-session-secret", "change-me-session-secret"}
DEV_IDENTITY_KEY = base64.urlsafe_b64encode(hashlib.sha256(b"ium-dev-identity-key").digest()).decode()
MIN_SECRET_LENGTH = 32


def production_problems(s: Settings) -> list[str]:
    """운영에 올리면 안 되는 설정을 사람이 읽을 수 있는 문장으로 돌려준다."""
    problems = []

    secret = s.secret_key.strip()
    if secret in DEV_SECRET_KEYS or len(secret) < MIN_SECRET_LENGTH:
        problems.append(
            "IUM_SECRET_KEY 가 개발용 값이거나 32자보다 짧습니다. 이 값을 아는 사람은 위원 세션을 "
            '위조할 수 있습니다. 생성: python -c "import secrets;print(secrets.token_urlsafe(48))"'
        )

    key = s.identity_key.strip()
    if not key or key == DEV_IDENTITY_KEY:
        problems.append(
            "IUM_IDENTITY_KEY 가 비어 있거나 개발용 고정키입니다. 이 키는 소스에서 계산할 수 있어 "
            "암호화된 식별정보를 누구나 풀 수 있습니다. 생성: "
            'python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"'
        )
    else:
        try:
            Fernet(key.encode())
        except ValueError:
            problems.append("IUM_IDENTITY_KEY 형식이 올바르지 않습니다 (Fernet 키가 아닙니다).")

    return problems


def enforce_production_settings(s: Settings) -> None:
    """운영 모드에서 개발용 설정이면 경고가 아니라 시작 거부.

    경고는 로그에 묻힌다. 개발용 키로 운영이 한 번 돌기 시작하면 그 사이 저장된 식별정보는
    이미 공개 키로 잠긴 셈이라, 나중에 키를 바꿔도 되돌릴 수 없다.
    """
    if not s.is_production:
        return
    problems = production_problems(s)
    if problems:
        raise RuntimeError(
            "IUM_ENV=production 인데 운영에 쓸 수 없는 설정이 있어 시작하지 않습니다:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )


settings = Settings()
enforce_production_settings(settings)
