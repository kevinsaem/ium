"""보관 기한이 지난 식별정보를 일괄 파기한다 — 서버에서 주기적으로 돌리는 명령.

    python -m app.purge_expired            # 대상만 보여 준다 (파기하지 않음)
    python -m app.purge_expired --apply    # 실제로 파기한다

위원회 결정(2026-09-19, 안건 01)대로 종결 후 보관 기간이 지나면 파기한다. 기간은 운영자가
화면에서 정한 값(Policy.identity_retention_months)을 그대로 쓴다.

기본이 '보여 주기'인 이유: 파기는 되돌릴 수 없다. cron 에 걸기 전에 무엇이 지워질지
사람이 한 번 보고 --apply 를 붙이게 한다.

파기 기록은 앱에서 누른 것과 같은 자리(identity_access_log)에 남는다. 행위자는 이 명령을
돌린 운영자 계정이며, --actor 로 지정한다. 누가 돌렸는지 없는 파기는 기록이 아니다.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from app import identity_service, retention
from app.db import SessionLocal, is_migrated
from app.models import Role, User
from app.timeutil import to_local


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="보관 기한이 지난 식별정보를 파기한다.")
    parser.add_argument("--apply", action="store_true", help="실제로 파기한다 (없으면 목록만)")
    parser.add_argument("--actor", help="파기 기록에 남길 운영자 이메일 (--apply 에 필수)")
    args = parser.parse_args(argv)

    if not is_migrated():
        sys.exit("DB 마이그레이션이 적용되지 않았습니다. 먼저 실행하세요: python -m alembic upgrade head")

    db = SessionLocal()
    try:
        policy = retention.current(db)
        months = policy.identity_retention_months
        targets = retention.expired(db, months)

        print(f"보관 기간: 종결 후 {months}개월")
        if not targets:
            print("기한이 지난 식별정보가 없습니다.")
            return

        print(f"기한 초과 {len(targets)}건:")
        for case in targets:
            due = retention.deadline(case, months)
            closed = to_local(case.closed_at).date() if case.closed_at else "-"
            print(f"  {case.code}  종결 {closed}  기한 {due}")

        if not args.apply:
            print("\n목록만 보여 주었습니다. 실제로 파기하려면 --apply --actor <운영자 이메일> 을 붙이세요.")
            return

        if not args.actor:
            sys.exit("--apply 에는 --actor <운영자 이메일> 이 필요합니다. 기록에 행위자를 남겨야 합니다.")

        actor = db.scalar(select(User).where(User.email == args.actor.strip().lower()))
        if actor is None or actor.role is not Role.OFFICE:
            sys.exit(f"운영자 계정을 찾을 수 없습니다: {args.actor}")

        for case in targets:
            identity_service.purge_expired_identity(
                db, case, actor, f"보관 기간 {months}개월 경과 (일괄 파기)"
            )
        print(f"\n{len(targets)}건의 식별정보를 파기했습니다. 비식별 케이스 기록과 통계는 그대로입니다.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
