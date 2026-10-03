"""retention policy — 식별정보 보관 기한

위원회 결정(2026-09-19, 안건 01): 케이스 종결 후 3개월까지 보관하고 파기한다. 기간은
"하드코딩으로 하지 말고" 운영자가 화면에서 바꿀 수 있어야 하므로 policy 테이블에 둔다.

case.closed_at 은 보관 기한의 시작점이다. 이 리비전 이전에 종결된 케이스는 값이 비어 있어
기한이 계산되지 않는다 — 다시 종결하거나 위원이 직접 파기하면 된다. 파일럿 전이라 그런
케이스는 시연 데이터뿐이다.

Revision ID: 2e66e4c67872
Revises: 635a9dae5258
Create Date: 2026-10-03 10:39:46.363825
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '2e66e4c67872'
down_revision: str | None = '635a9dae5258'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('policy',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('identity_retention_months', sa.Integer(), server_default=sa.text('3'), nullable=False),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['updated_by_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('case', schema=None) as batch_op:
        batch_op.add_column(sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('case', schema=None) as batch_op:
        batch_op.drop_column('closed_at')

    op.drop_table('policy')
