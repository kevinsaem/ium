"""device memory and donor notes — 기기 기억 30일, 후원자 메모, 주소·우편번호

위원회 결정(2026-10-17, 안건 13):
- "본인 기기는 한동안 인증 없이 사용하고 30일 경과 시 재인증한다." -> trusted_device
- "후원자별 메모를 누적 추가할 수 있으며 각 메모엔 날짜, 시간, 작성자, 내용이 함께
  기록된다." -> donor_note
- 선택 정보에 주소·우편번호 -> shop.postal_code (주소 컬럼은 이미 있었다)

trusted_device 에는 토큰 해시만 넣는다. DB 가 유출돼도 그 값으로 로그인할 수 없다.

Revision ID: 88aebd159ae3
Revises: bcf30e2e5909
Create Date: 2026-10-24 10:35:16.067449
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '88aebd159ae3'
down_revision: str | None = 'bcf30e2e5909'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('donor_note',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('donor_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['user.id'], ),
    sa.ForeignKeyConstraint(['donor_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('donor_note', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_donor_note_author_id'), ['author_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_donor_note_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_donor_note_donor_id'), ['donor_id'], unique=False)

    op.create_table('trusted_device',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('trusted_device', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_trusted_device_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_trusted_device_token_hash'), ['token_hash'], unique=True)
        batch_op.create_index(batch_op.f('ix_trusted_device_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('shop', schema=None) as batch_op:
        batch_op.add_column(sa.Column('postal_code', sa.String(length=10), nullable=True))



def downgrade() -> None:
    with op.batch_alter_table('shop', schema=None) as batch_op:
        batch_op.drop_column('postal_code')

    with op.batch_alter_table('trusted_device', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_trusted_device_user_id'))
        batch_op.drop_index(batch_op.f('ix_trusted_device_token_hash'))
        batch_op.drop_index(batch_op.f('ix_trusted_device_expires_at'))

    op.drop_table('trusted_device')
    with op.batch_alter_table('donor_note', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_donor_note_donor_id'))
        batch_op.drop_index(batch_op.f('ix_donor_note_created_at'))
        batch_op.drop_index(batch_op.f('ix_donor_note_author_id'))

    op.drop_table('donor_note')
