"""협의체(테넌트) 골격 — council 테이블과 자료의 소속

여러 동의 협의체가 한 시스템 위에서 각자 활동하게 하는 첫 단계다. 기능을 먼저 올리고
나중에 협의체를 끼워 넣으면 이미 만든 모든 조회를 다시 훑어야 하므로, 경계를 먼저 깐다.

기존 자료는 전부 선부3동 협의체로 옮긴다. 1차 구현이 선부3동 하나를 전제했으니 사실
그대로다. 사용자(user)만 소속이 비어 있을 수 있다 — 슈퍼 관리자가 경계 밖이기 때문이다.

컬럼을 NOT NULL 로 두는 게 중요하다. 비워 둘 수 있게 하면 소속을 안 찍은 자료가 조용히
생기고, 그건 조회에서 "아무 협의체에도 안 보이는 자료" 로 끝나거나 더 나쁘게는 경계를
넘어 보인다. 그래서 세 걸음으로 간다 — 컬럼 추가(널 허용) → 채우기 → NOT NULL.

Revision ID: d5ae734f2061
Revises: 88aebd159ae3
Create Date: 2026-10-24 10:57:19.894306
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'd5ae734f2061'
down_revision: str | None = '88aebd159ae3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# app/models/council.py 의 DEFAULT_SLUG 와 같은 값. 마이그레이션은 그때의 코드로 고정돼야
# 하므로 import 하지 않고 적어 둔다 — 나중에 상수가 바뀌어도 이 마이그레이션은 그대로다.
DEFAULT_SLUG = "sunbu3"
DEFAULT_REGION = "안산시 단원구"
DEFAULT_DONG = "선부3동"

# 소속을 갖는 테이블. policy 는 협의체마다 한 행이라 유니크 제약이 더 붙는다.
SCOPED = ["case", "identity_access_log", "match", "offer", "policy", "shop"]


def upgrade() -> None:
    op.create_table(
        'council',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('region', sa.String(length=60), nullable=False),
        sa.Column('dong', sa.String(length=40), nullable=False),
        sa.Column('region_code', sa.String(length=20), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['approved_by_id'], ['user.id'], name='fk_council_approved_by'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('council', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_council_slug'), ['slug'], unique=True)

    # 파일럿 협의체. 이미 승인된 것으로 둔다 — 승인 화면이 생기기 전부터 돌아가던
    # 협의체이고, 미승인으로 두면 기존 자료 전체가 잠긴다.
    council = sa.table(
        'council',
        sa.column('id', sa.Integer),
        sa.column('slug', sa.String),
        sa.column('region', sa.String),
        sa.column('dong', sa.String),
        sa.column('approved_at', sa.DateTime),
        sa.column('is_active', sa.Boolean),
    )
    op.execute(
        council.insert().values(
            slug=DEFAULT_SLUG,
            region=DEFAULT_REGION,
            dong=DEFAULT_DONG,
            approved_at=sa.func.now(),
            is_active=True,
        )
    )
    default_id = op.get_bind().execute(
        sa.text("SELECT id FROM council WHERE slug = :slug"), {"slug": DEFAULT_SLUG}
    ).scalar_one()

    for table in SCOPED:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('council_id', sa.Integer(), nullable=True))
            batch_op.create_index(
                batch_op.f(f'ix_{table}_council_id'), ['council_id'], unique=False
            )
            batch_op.create_foreign_key(
                f'fk_{table}_council', 'council', ['council_id'], ['id']
            )
        op.execute(
            sa.text(f'UPDATE "{table}" SET council_id = :cid').bindparams(cid=default_id)
        )
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('council_id', existing_type=sa.Integer(), nullable=False)
            if table == 'policy':
                batch_op.create_unique_constraint('uq_policy_council', ['council_id'])
            if table == 'case':
                # 케이스 코드는 협의체 안에서만 유일하다. 전역 유일로 두면 다른 동이
                # 쓰는 코드가 중복 오류로 드러난다.
                batch_op.drop_index(batch_op.f('ix_case_code'))
                batch_op.create_index(batch_op.f('ix_case_code'), ['code'], unique=False)
                batch_op.create_unique_constraint(
                    'uq_case_council_code', ['council_id', 'code']
                )

    # 사용자는 소속이 없을 수 있다 (슈퍼 관리자). 기존 계정은 모두 선부3동이다.
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('council_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_council_id'), ['council_id'], unique=False)
        batch_op.create_foreign_key('fk_user_council', 'council', ['council_id'], ['id'])
    op.execute(sa.text('UPDATE "user" SET council_id = :cid').bindparams(cid=default_id))


def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_constraint('fk_user_council', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_user_council_id'))
        batch_op.drop_column('council_id')

    for table in reversed(SCOPED):
        with op.batch_alter_table(table, schema=None) as batch_op:
            if table == 'case':
                batch_op.drop_constraint('uq_case_council_code', type_='unique')
                batch_op.drop_index(batch_op.f('ix_case_code'))
                batch_op.create_index(batch_op.f('ix_case_code'), ['code'], unique=True)
            if table == 'policy':
                batch_op.drop_constraint('uq_policy_council', type_='unique')
            batch_op.drop_constraint(f'fk_{table}_council', type_='foreignkey')
            batch_op.drop_index(batch_op.f(f'ix_{table}_council_id'))
            batch_op.drop_column('council_id')

    with op.batch_alter_table('council', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_council_slug'))
    op.drop_table('council')
