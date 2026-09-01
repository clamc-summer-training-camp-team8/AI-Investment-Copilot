"""Persist latest hypothesis health state for company pages.

Decision batches already store a historical health snapshot.  These columns
keep the latest per-hypothesis research state directly on the hypothesis so
company-level maintenance pages can display it without replaying audit logs.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0026_hypothesis_health_state"
down_revision: str | None = "0025_research_output_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("hypothesis")}
    if "health_state" not in existing:
        op.add_column("hypothesis", sa.Column("health_state", sa.String(length=32)))
    if "health_reason" not in existing:
        op.add_column("hypothesis", sa.Column("health_reason", sa.Text()))
    if "health_support_count" not in existing:
        op.add_column("hypothesis", sa.Column("health_support_count", sa.Integer(), nullable=False, server_default="0"))
    if "health_conflict_count" not in existing:
        op.add_column("hypothesis", sa.Column("health_conflict_count", sa.Integer(), nullable=False, server_default="0"))
    if "health_updated_at" not in existing:
        op.add_column("hypothesis", sa.Column("health_updated_at", sa.DateTime()))

    bind.execute(
        sa.text(
            "UPDATE hypothesis SET "
            "health_state = COALESCE(health_state, status), "
            "health_reason = COALESCE(health_reason, '历史假设状态迁移生成，后续研究决策批次会刷新。')"
        )
    )


def downgrade() -> None:
    for name in (
        "health_updated_at",
        "health_conflict_count",
        "health_support_count",
        "health_reason",
        "health_state",
    ):
        op.drop_column("hypothesis", name)
