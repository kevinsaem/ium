"""drop credit — 증빙(기부금 영수증·봉사시간) 테이블 제거

위원회 결정(안건 03): 물품·서비스 나눔은 1365 봉사시간으로 인정되지 않고, 협의체는
기부금 영수증 발급 주체가 될 수 없다. 그래서 이 시스템에서 다루지 않는다.

익명 감사 메시지(thanks_message)는 증빙이 아니라 별개 기능이므로 그대로 둔다.

downgrade 는 테이블을 다시 만들지만 안에 있던 신청 기록은 돌아오지 않는다.

Revision ID: 3e793fc61b5d
Revises: 1d7ef257b1ba
Create Date: 2026-09-19 11:37:02.463836
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '3e793fc61b5d'
down_revision: str | None = '1d7ef257b1ba'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('credit', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_credit_donor_id'))
        batch_op.drop_index(batch_op.f('ix_credit_status'))

    op.drop_table('credit')


def downgrade() -> None:
    op.create_table('credit',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('donor_id', sa.INTEGER(), nullable=False),
    sa.Column('kind', sa.VARCHAR(length=9), nullable=False),
    sa.Column('status', sa.VARCHAR(length=9), nullable=False),
    sa.Column('period_label', sa.VARCHAR(length=40), nullable=False),
    sa.Column('volunteer_hours', sa.INTEGER(), nullable=True),
    sa.Column('amount_krw', sa.INTEGER(), nullable=True),
    sa.Column('issued_note', sa.TEXT(), nullable=True),
    sa.Column('processed_by_id', sa.INTEGER(), nullable=True),
    sa.Column('created_at', sa.DATETIME(), server_default=sa.func.now(), nullable=False),
    sa.Column('updated_at', sa.DATETIME(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['donor_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['processed_by_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('credit', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_credit_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_credit_donor_id'), ['donor_id'], unique=False)

