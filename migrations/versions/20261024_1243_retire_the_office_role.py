"""운영자 역할 폐기 — 남은 계정을 위원으로 옮긴다

관리자 = 매니저 = 협의체당 한 사람으로 정리되면서(2026-10-24 결정) 운영자가 하던 일이
전부 관리자에게 왔다. 역할을 하나 줄이면 개인정보 사전 승인에서 설명할 것도 하나 줄어든다.

스키마는 바뀌지 않는다. role 컬럼은 Enum(native_enum=False) 라 VARCHAR 이고, 값이 하나
줄어도 길이가 그대로다. 바뀌는 것은 데이터다 — 남아 있는 운영자 계정을 위원으로 옮긴다.

관리자 권한은 그 협의체에 관리자가 없을 때만 준다. 이미 있으면 평범한 위원으로 둔다 —
협의체당 한 사람이라는 조건이 이 마이그레이션에서 깨지면 안 된다.

계정을 지우지 않는 이유는 기록이다. 그 계정이 발급한 위원과 승인한 후원자, 열람 기록의
행위자가 전부 이 id 를 가리키고 있다. 지우면 "누가 했는가" 가 비어 버린다.

Revision ID: 8c1d4f0a2b73
Revises: 024d39687576
Create Date: 2026-10-24 12:43:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '8c1d4f0a2b73'
down_revision: str | None = '024d39687576'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum(native_enum=False) 는 값이 아니라 **이름**을 저장한다 — 'office' 가 아니라 'OFFICE'.
# 이걸 틀리면 UPDATE 가 0행을 고치고 조용히 넘어간다 (이전 마이그레이션에서 겪었다).
OFFICE = "OFFICE"
MEMBER = "MEMBER"


def upgrade() -> None:
    bind = op.get_bind()

    # 관리자가 없는 협의체의 운영자 한 명씩만 관리자로 올린다.
    rows = bind.execute(
        sa.text(
            """
            SELECT o.id, o.council_id
              FROM "user" o
             WHERE o.role = :office
               AND o.is_active = 1
               AND NOT EXISTS (
                   SELECT 1 FROM "user" m
                    WHERE m.council_id = o.council_id
                      AND m.role = :member
                      AND m.is_manager = 1
                      AND m.is_active = 1
               )
             ORDER BY o.id
            """
        ),
        {"office": OFFICE, "member": MEMBER},
    ).fetchall()

    promoted: set[int] = set()
    seen_councils: set[int] = set()
    for user_id, council_id in rows:
        if council_id in seen_councils:
            continue
        seen_councils.add(council_id)
        promoted.add(user_id)

    op.execute(
        sa.text(
            """
            UPDATE "user"
               SET role = :member,
                   is_manager = 0,
                   approved_at = COALESCE(approved_at, CURRENT_TIMESTAMP)
             WHERE role = :office
            """
        ).bindparams(member=MEMBER, office=OFFICE)
    )

    for user_id in promoted:
        op.execute(
            sa.text('UPDATE "user" SET is_manager = 1 WHERE id = :uid').bindparams(uid=user_id)
        )


def downgrade() -> None:
    """되돌릴 수 없다.

    어느 위원이 원래 운영자였는지는 남겨 두지 않았다. 남기려면 컬럼을 하나 더 두어야
    하는데, 폐기하는 역할을 위해 컬럼을 늘리는 것은 방향이 반대다.

    내려가야 한다면 이 마이그레이션 이전의 백업에서 복구할 것.
    """
    raise NotImplementedError(
        "운영자 역할 폐기는 되돌릴 수 없습니다. 이전 백업에서 복구하세요."
    )
