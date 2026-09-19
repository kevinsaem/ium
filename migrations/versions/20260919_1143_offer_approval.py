"""offer approval — 승인의 자리를 매칭에서 나눔글로 옮긴다

위원회 결정(2026-09-19, 안건 05): 위원 여럿이 매칭을 승인하는 대신, 운영팀이 나눔글의
노출 여부를 결정한다. 그래서 match_approval 테이블을 내리고 offer 에 심사 기록을 붙인다.

기존 나눔글은 손대지 않는다. 상태 문자열('open' 등)이 그대로 남으므로 이미 올라와 있던
나눔은 계속 노출된다 — 승인 대기(PENDING)는 이 리비전 이후 새로 올라오는 글에만 붙는다.

match_approval 을 내리면 그동안의 승인 기록도 함께 사라진다. 파일럿 전이라 운영 데이터가
없어 그대로 내리지만, 운영 중이라면 먼저 따로 보관해야 한다.

Revision ID: 635a9dae5258
Revises: 3e793fc61b5d
Create Date: 2026-09-19 11:43:03.242437
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '635a9dae5258'
down_revision: str | None = '3e793fc61b5d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('match_approval', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_match_approval_approver_id'))
        batch_op.drop_index(batch_op.f('ix_match_approval_match_id'))

    op.drop_table('match_approval')
    with op.batch_alter_table('offer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviewed_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('review_note', sa.Text(), nullable=True))
        batch_op.create_foreign_key('fk_offer_reviewed_by', 'user', ['reviewed_by_id'], ['id'])



def downgrade() -> None:
    with op.batch_alter_table('offer', schema=None) as batch_op:
        batch_op.drop_constraint('fk_offer_reviewed_by', type_='foreignkey')
        batch_op.drop_column('review_note')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('reviewed_by_id')

    op.create_table('match_approval',
    sa.Column('id', sa.INTEGER(), nullable=False),
    sa.Column('match_id', sa.INTEGER(), nullable=False),
    sa.Column('approver_id', sa.INTEGER(), nullable=False),
    sa.Column('comment', sa.VARCHAR(length=200), nullable=True),
    sa.Column('approved_at', sa.DATETIME(), nullable=False),
    sa.ForeignKeyConstraint(['approver_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['match_id'], ['match.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('match_id', 'approver_id', name=op.f('uq_match_approver'))
    )
    with op.batch_alter_table('match_approval', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_match_approval_match_id'), ['match_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_match_approval_approver_id'), ['approver_id'], unique=False)

