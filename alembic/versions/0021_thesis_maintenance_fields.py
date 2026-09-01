"""Add company-page maintenance fields to thesis."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021_thesis_maintenance_fields"
down_revision: str | None = "0020_financial_metric_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 远程环境可能已通过无停机补丁预先创建列，迁移保持幂等，避免重复执行失败。
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("thesis")}
    if "investment_rating" not in existing:
        op.add_column("thesis", sa.Column("investment_rating", sa.String(length=32)))
    if "target_price" not in existing:
        op.add_column("thesis", sa.Column("target_price", sa.Numeric(20, 6)))
    if "observation_period" not in existing:
        op.add_column("thesis", sa.Column("observation_period", sa.String(length=128)))


def downgrade() -> None:
    op.execute('ALTER TABLE thesis DROP COLUMN IF EXISTS observation_period')
    op.execute('ALTER TABLE thesis DROP COLUMN IF EXISTS target_price')
    op.execute('ALTER TABLE thesis DROP COLUMN IF EXISTS investment_rating')
