"""manager flag — 매니저는 위원에게 주는 권한

위원회 결정(2026-10-17, 안건 14): "위원 중 한 명이 매니저 역할을 맡으며" — 그래서 Role 을
넷으로 늘리지 않고 위원에게 주는 플래그로 둔다. 누가 맡을지는 정례회의에서 정하고 운영자가
화면에서 반영한다.

기존 위원은 모두 is_manager=False 로 남는다. 운영을 시작하기 전에 한 명을 지정해야 한다.

Revision ID: 95ceafcd2001
Revises: 55b20acc1dee
Create Date: 2026-10-17 12:05:33.783132
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '95ceafcd2001'
down_revision: str | None = '55b20acc1dee'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_manager', sa.Boolean(), server_default=sa.text('0'), nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('is_manager')

