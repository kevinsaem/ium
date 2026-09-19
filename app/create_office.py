"""첫 운영자 계정 만들기 — 운영 서버에서 쓰는 명령.

    python -m app.create_office --email office@example.kr --name "협의체 사무국"

seed.py 와 달리 운영 모드에서도 돈다. 위원 계정은 이 운영자가 앱 화면에서 발급한다.

비밀번호는 명령줄 인자로 받지 않는다 — 셸 기록과 프로세스 목록에 남기 때문이다.
터미널에서는 화면에 보이지 않게 두 번 입력받고, 파이프로 들어오면 첫 줄을 쓴다.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app import accounts
from app.db import SessionLocal, is_migrated


def _read_password() -> str:
    if sys.stdin.isatty():
        first = getpass.getpass("비밀번호: ")
        second = getpass.getpass("비밀번호 확인: ")
        if first != second:
            sys.exit("두 비밀번호가 서로 다릅니다.")
        return first
    return sys.stdin.readline().rstrip("\r\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="이음 운영자 계정을 만든다.")
    parser.add_argument("--email", required=True, help="로그인에 쓸 이메일")
    parser.add_argument("--name", required=True, help="화면에 보일 이름")
    args = parser.parse_args(argv)

    if not is_migrated():
        sys.exit("DB 마이그레이션이 적용되지 않았습니다. 먼저 실행하세요: python -m alembic upgrade head")

    password = _read_password()
    db = SessionLocal()
    try:
        user = accounts.create_office(db, name=args.name, email=args.email, password=password)
        print(f"운영자 계정을 만들었습니다: {user.name} <{user.email}>")
    except accounts.AccountError as exc:
        sys.exit(str(exc))
    finally:
        db.close()


if __name__ == "__main__":
    main()
