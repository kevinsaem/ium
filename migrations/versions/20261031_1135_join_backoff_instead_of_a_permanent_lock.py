"""위원 가입 잠금을 늘어나는 대기 시간으로

영구 잠금을 쓰지 않는다. 지나가는 사람이 아무 코드나 다섯 번 넣으면 그 동의 위원 모집이
관리자가 손을 쓸 때까지 멈췄다. 초대 코드는 8,500억 가지 중 몇 개뿐이라 속도만 묶어도
추측이 성립하지 않으므로, 잠금 대신 대기 시간을 쓴다 (app/models/council.py 의 JOIN_BACKOFF).

컬럼 하나의 이름이 바뀐다. '잠긴 시각'(join_locked_at)이 '마지막 실패 시각'
(join_last_failed_at)이 된다. 값의 뜻이 달라졌으니 이름도 같이 바꿔야 한다 — 그대로 두면
다음에 읽는 사람이 '잠긴 시각' 으로 읽고, 실패가 또 들어올 때마다 갱신되는 것을 버그로 본다.

남아 있는 값은 그대로 옮긴다. 마지막 실패 시각으로 읽어도 틀리지 않고(잠긴 그 순간이
마지막 실패였다), 24시간이 지났으면 어차피 잊힌다.

Revision ID: 1efda30b311b
Revises: 8c1d4f0a2b73
Create Date: 2026-10-31 11:35:52.439329
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '1efda30b311b'
down_revision: str | None = '8c1d4f0a2b73'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('council', schema=None) as batch_op:
        batch_op.alter_column(
            'join_locked_at',
            new_column_name='join_last_failed_at',
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('council', schema=None) as batch_op:
        batch_op.alter_column(
            'join_last_failed_at',
            new_column_name='join_locked_at',
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
