"""account provisioning — 계정 기록 테이블과 비밀번호 변경 강제 플래그

autogenerate 가 만든 server_default 를 SQLite 표현에서 양쪽 DB 에서 도는 표현으로 바꿨다
(text('0') -> sa.false(), '(CURRENT_TIMESTAMP)' -> sa.func.now()). Postgres 전환 예정이라서다.

기존 계정은 must_change_password=False 로 남는다. 이미 본인이 정한 비밀번호를 쓰고 있으므로
갑자기 변경을 요구할 이유가 없다.

Revision ID: 1d7ef257b1ba
Revises: b8fba877bac2
Create Date: 2026-09-19 10:42:35.382250
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '1d7ef257b1ba'
down_revision: str | None = 'b8fba877bac2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('account_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=30), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('account_event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_account_event_actor_id'), ['actor_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_account_event_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_account_event_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), server_default=sa.false(), nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('must_change_password')

    with op.batch_alter_table('account_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_account_event_user_id'))
        batch_op.drop_index(batch_op.f('ix_account_event_created_at'))
        batch_op.drop_index(batch_op.f('ix_account_event_actor_id'))

    op.drop_table('account_event')
