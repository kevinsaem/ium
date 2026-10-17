"""donor approval — 승인을 나눔글에서 후원자로 옮긴다

위원회 결정(2026-10-17, 안건 10·16): 나눔글을 건건이 검증해 공개 여부를 정하는 방식은
폐기한다. 대신 후원자 자체를 검증한다. 안건 05 를 뒤집은 것이다.

- offer 의 심사 기록 컬럼을 내린다.
- user 에 승인 기록을 붙인다 (후원자에게만 의미가 있다).

데이터 변환이 둘 있다.
- 없어진 상태값 정리: 'pending' -> 'open', 'rejected' -> 'closed'. 그대로 두면 앱이
  읽을 수 없는 값이 남는다.
- 기존 후원자는 승인된 것으로 둔다. 예전 방식에서 이미 나눔을 올리고 있던 사람들이라,
  승인 안 된 상태로 바꾸면 그 가게들이 조용히 매칭 후보에서 빠진다.

Revision ID: a126c2a5b598
Revises: 95ceafcd2001
Create Date: 2026-10-17 12:18:10.379372
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a126c2a5b598'
down_revision: str | None = '95ceafcd2001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 없어진 상태값을 먼저 정리한다. 컬럼을 내린 뒤에는 review_note 를 참고할 수 없다.
    # Enum(native_enum=False) 은 값이 아니라 '이름'을 저장한다 — PENDING, 소문자 pending 아님.
    op.execute("UPDATE offer SET status = 'OPEN' WHERE status = 'PENDING'")
    op.execute("UPDATE offer SET status = 'CLOSED' WHERE status = 'REJECTED'")

    with op.batch_alter_table('offer', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_offer_reviewed_by'), type_='foreignkey')
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('review_note')
        batch_op.drop_column('reviewed_at')

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('approved_by_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_user_approved_by', 'user', ['approved_by_id'], ['id'])

    # 예전 방식에서 이미 활동하던 후원자는 승인된 것으로 둔다.
    op.execute(
        "UPDATE user SET approved_at = CURRENT_TIMESTAMP "
        "WHERE role = 'DONOR' AND approved_at IS NULL"
    )



def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_approved_by', type_='foreignkey')
        batch_op.drop_column('approved_by_id')
        batch_op.drop_column('approved_at')

    with op.batch_alter_table('offer', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reviewed_at', sa.DATETIME(), nullable=True))
        batch_op.add_column(sa.Column('review_note', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.INTEGER(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_offer_reviewed_by'), 'user', ['reviewed_by_id'], ['id'])

