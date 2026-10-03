"""donor pin login — 후원자는 휴대폰 번호와 숫자 4자리로 로그인한다

위원회 결정(2026-09-19, 안건 07): 후원자는 스스로 아주 단순하게 가입하고, 휴대폰 번호와
숫자 4자리로 로그인한다. 이메일은 받지 않으므로 user.email 을 비울 수 있게 한다.
user.phone 은 로그인 아이디가 되므로 고유해야 한다.

기존 시드 후원자는 이메일만 있고 번호가 없다. 번호가 NULL 인 행은 고유 인덱스에 걸리지
않으므로 그대로 남고, 이메일 로그인도 계속 된다 — 번호를 넣어 주면 그때부터 숫자 로그인이
된다. 운영 데이터는 아직 없다.

failed_logins·locked_until 은 숫자 4자리를 하나씩 넣어 보는 시도를 막기 위한 것이다.
1만 가지뿐이라 횟수 제한 없이는 뚫린다.

Revision ID: 55b20acc1dee
Revises: 33b537b4b5ba
Create Date: 2026-10-03 10:59:58.497403
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '55b20acc1dee'
down_revision: str | None = '33b537b4b5ba'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('failed_logins', sa.Integer(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.alter_column('email',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_user_phone'), ['phone'], unique=True)



def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_phone'))
        batch_op.alter_column('email',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
        batch_op.drop_column('locked_until')
        batch_op.drop_column('failed_logins')

