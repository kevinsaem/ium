"""retention three years — 보관 기간 3개월에서 3년으로

위원회 결정(2026-10-17, 안건 09): "식별정보를 전부 파기하지 않는다. 후원받는 분의 동의를
받아 누가 언제 무엇을 받았는지 기록을 3년간 보관한다." 1차(안건 01)의 3개월을 뒤집었다.

autogenerate 가 빈 리비전을 만든다 — 파이썬 기본값과 server_default 변경은 스키마 비교로
잡히지 않는다. 그래서 직접 적는다.

이미 3개월로 들어가 있는 행만 올린다. 운영자가 다른 값으로 바꿔 두었다면 그 판단을
덮어쓰지 않는다.

Revision ID: bcf30e2e5909
Revises: 587dd8bc0ca9
Create Date: 2026-10-17 12:53:59.113024
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'bcf30e2e5909'
down_revision: str | None = '587dd8bc0ca9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("policy", schema=None) as batch_op:
        batch_op.alter_column(
            "identity_retention_months",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("36"),
        )
    op.execute("UPDATE policy SET identity_retention_months = 36 WHERE identity_retention_months = 3")


def downgrade() -> None:
    with op.batch_alter_table("policy", schema=None) as batch_op:
        batch_op.alter_column(
            "identity_retention_months",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("3"),
        )
    op.execute("UPDATE policy SET identity_retention_months = 3 WHERE identity_retention_months = 36")
