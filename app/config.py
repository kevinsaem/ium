"""애플리케이션 설정.

MATCH_APPROVAL_MODE 는 슬라이드 6 안건 ⑤(매칭 승인 프로세스)가 아직 미정이라
코드가 아니라 설정으로 바꿀 수 있게 빼 두었다. 위원회 결정이 나면 .env 한 줄만 고치면 된다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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

    # member    : 위원이 제안하면 즉시 승인
    # committee : 협의체 공동 결정 — committee_approvals 명 이상의 승인 필요
    match_approval_mode: str = _env("IUM_MATCH_APPROVAL_MODE", "committee")
    committee_approvals: int = int(_env("IUM_COMMITTEE_APPROVALS", "2"))

    # 파일럿 대상 동
    dong: str = _env("IUM_DONG", "선부3동")


settings = Settings()
