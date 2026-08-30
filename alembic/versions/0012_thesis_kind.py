"""Separate canonical theses from observation snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_thesis_kind"
down_revision: str | None = "0011_ai_runtime_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("thesis", sa.Column("thesis_kind", sa.String(16), nullable=False, server_default="canonical"))
    op.add_column("thesis", sa.Column("thesis_series_id", sa.String(64), nullable=True))
    # 行业评测数据的季度卡片保留，但不再作为当前主投资逻辑展示。
    op.execute(
        "UPDATE thesis SET thesis_kind = 'observation', thesis_series_id = security_id "
        "WHERE thesis_id ~ '^THS-[0-9]+-20[0-9]{2}Q[1-4]$'"
    )


def downgrade() -> None:
    op.drop_column("thesis", "thesis_series_id")
    op.drop_column("thesis", "thesis_kind")
