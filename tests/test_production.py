"""운영 모드 안전장치 테스트.

저장소가 공개되어 있으므로 소스에 적힌 개발용 키는 비밀이 아니다. 그 키로 운영이 돌면
세션을 위조해 위원으로 들어오거나, 암호화된 식별정보를 누구나 풀 수 있다.
IUM_ENV=production 에서는 그런 설정으로 '경고 후 계속'이 아니라 '시작 거부'여야 한다.

시작 거부는 import 시점에 일어나므로, 실제로 새 파이썬 프로세스를 띄워 확인한다.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.config import DEV_IDENTITY_KEY, Settings, enforce_production_settings, production_problems

ROOT = Path(__file__).resolve().parent.parent


def _good_keys() -> dict[str, str]:
    return {
        "IUM_SECRET_KEY": secrets.token_urlsafe(48),
        "IUM_IDENTITY_KEY": Fernet.generate_key().decode(),
    }


def _settings(**overrides) -> Settings:
    values = {"env": "production"}
    values.update({"secret_key": _good_keys()["IUM_SECRET_KEY"], "identity_key": Fernet.generate_key().decode()})
    values.update(overrides)
    return Settings(**values)


def _python(args: list[str], env_overrides: dict[str, str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(ROOT), **env_overrides}
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


# --- 설정 검사 -------------------------------------------------------------


def test_good_production_settings_have_no_problems():
    assert production_problems(_settings()) == []


@pytest.mark.parametrize(
    "secret",
    ["dev-only-insecure-session-secret", "change-me-session-secret", "too-short"],
)
def test_dev_or_short_session_secret_is_a_problem(secret):
    problems = production_problems(_settings(secret_key=secret))
    assert len(problems) == 1 and "IUM_SECRET_KEY" in problems[0]


@pytest.mark.parametrize("key", ["", "   ", DEV_IDENTITY_KEY])
def test_missing_or_dev_identity_key_is_a_problem(key):
    problems = production_problems(_settings(identity_key=key))
    assert len(problems) == 1 and "IUM_IDENTITY_KEY" in problems[0]


def test_malformed_identity_key_is_a_problem():
    problems = production_problems(_settings(identity_key="not-a-fernet-key"))
    assert len(problems) == 1 and "형식" in problems[0]


def test_enforce_lists_every_problem_at_once():
    """하나 고치고 다시 띄우고 또 하나 고치는 일이 없게, 전부 한 번에 알려 준다."""
    bad = _settings(secret_key="dev-only-insecure-session-secret", identity_key="")
    with pytest.raises(RuntimeError) as exc:
        enforce_production_settings(bad)
    assert "IUM_SECRET_KEY" in str(exc.value)
    assert "IUM_IDENTITY_KEY" in str(exc.value)


def test_development_mode_keeps_working_with_dev_values():
    enforce_production_settings(
        _settings(env="development", secret_key="dev-only-insecure-session-secret", identity_key="")
    )


# --- 실제 프로세스 시작 ----------------------------------------------------


def test_server_refuses_to_start_in_production_with_dev_keys():
    result = _python(
        ["-c", "import app.main"],
        {"IUM_ENV": "production", "IUM_SECRET_KEY": "dev-only-insecure-session-secret", "IUM_IDENTITY_KEY": ""},
    )
    assert result.returncode != 0
    assert "시작하지 않습니다" in result.stderr
    assert "IUM_SECRET_KEY" in result.stderr
    assert "IUM_IDENTITY_KEY" in result.stderr


def test_server_starts_in_production_with_real_keys():
    result = _python(["-c", "import app.main"], {"IUM_ENV": "production", **_good_keys()})
    assert result.returncode == 0, result.stderr


_COOKIE_FLAG = (
    "import app.main as m\n"
    "from starlette.middleware.sessions import SessionMiddleware\n"
    "mw = next(x for x in m.app.user_middleware if x.cls is SessionMiddleware)\n"
    "opts = getattr(mw, 'kwargs', None) or getattr(mw, 'options', {})\n"
    "print('https_only=%s' % opts.get('https_only'))\n"
)


def test_session_cookie_is_https_only_in_production():
    result = _python(["-c", _COOKIE_FLAG], {"IUM_ENV": "production", **_good_keys()})
    assert result.returncode == 0, result.stderr
    assert "https_only=True" in result.stdout


def test_session_cookie_still_works_over_http_in_development():
    result = _python(["-c", _COOKIE_FLAG], {"IUM_ENV": "development", **_good_keys()})
    assert result.returncode == 0, result.stderr
    assert "https_only=False" in result.stdout


def test_seed_refuses_to_run_in_production_before_deleting_anything(tmp_path):
    # --reset 은 작업 폴더의 ium.db 를 지운다. 거부가 그보다 먼저 일어나야 한다.
    sentinel = tmp_path / "ium.db"
    sentinel.write_text("운영 데이터라고 치자", encoding="utf-8")

    result = _python(
        [str(ROOT / "seed.py"), "--reset"],
        {
            "IUM_ENV": "production",
            "IUM_DATABASE_URL": f"sqlite:///{(tmp_path / 'other.db').as_posix()}",
            **_good_keys(),
        },
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "시드를 실행하지 않습니다" in result.stderr
    assert sentinel.exists()
    assert not (tmp_path / "other.db").exists()


# --- 로그인 화면 -----------------------------------------------------------


def test_login_page_hides_the_account_list_in_production(client, seeded, monkeypatch):
    from app import config

    assert "office@ium.test" in client.get("/login").text  # 개발에서는 바로가기가 보인다

    monkeypatch.setattr(config.settings, "env", "production")
    body = client.get("/login").text

    assert "개발용 계정" not in body
    assert "office@ium.test" not in body
    assert "이관희" not in body
