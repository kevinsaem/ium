"""manager unlock and team contact — 잠금은 매니저가 푼다

위원회 결정(2026-10-17, 안건 15): 5회 오류 시 계정 잠금, 잠김은 매니저 화면에 안내되고
매니저가 해제한다. 운영팀 연락처는 매니저가 설정 화면에서 직접 입력한다.

locked_until(10분 뒤 자동 해제) 을 locked_at(잠긴 시각) 으로 바꾼다. 의미가 바뀌었으므로
이름도 바꿨다 — 자동 해제로 두면 매니저 화면에 아무것도 뜨지 않아 '매니저가 해제한다'는
결정이 사실상 없는 기능이 된다.

컬럼을 갈아 끼우므로 지금 잠겨 있는 계정은 풀린다. 예전 잠금은 10분이면 저절로 풀리는
것이었으니 그대로 두는 편이 맞다 — 무기한 잠금으로 승계하면 영문 모르고 막힌 사람이 생긴다.

Revision ID: 587dd8bc0ca9
Revises: a126c2a5b598
Create Date: 2026-10-17 12:33:02.377666
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '587dd8bc0ca9'
down_revision: str | None = 'a126c2a5b598'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('policy', schema=None) as batch_op:
        batch_op.add_column(sa.Column('team_contact', sa.String(length=120), nullable=True))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_column('locked_until')



def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('locked_until', sa.DATETIME(), nullable=True))
        batch_op.drop_column('locked_at')

    with op.batch_alter_table('policy', schema=None) as batch_op:
        batch_op.drop_column('team_contact')

