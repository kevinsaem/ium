"""pilot window — 파일럿 기간

위원회 결정(2026-09-19, 안건 04): 파일럿 기간은 1개월. 시작일은 "완성되고 나서 해야 되는
거니까" 회의에서 정하지 않았으므로 비워 두고 운영자가 화면에서 넣는다. 비어 있는 동안
지표는 누적으로 집계된다.

Revision ID: 33b537b4b5ba
Revises: 2e66e4c67872
Create Date: 2026-10-03 10:47:16.373411
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '33b537b4b5ba'
down_revision: str | None = '2e66e4c67872'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('policy', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pilot_start', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('pilot_months', sa.Integer(), server_default=sa.text('1'), nullable=False))



def downgrade() -> None:
    with op.batch_alter_table('policy', schema=None) as batch_op:
        batch_op.drop_column('pilot_months')
        batch_op.drop_column('pilot_start')

