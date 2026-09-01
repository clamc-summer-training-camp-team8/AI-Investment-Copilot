"""Persist structured research outputs beside status suggestions.

The suggestion log used to contain only a target status.  A batch can also
produce a non-blocking reminder or a hypothesis-health snapshot, so these
fields make the three outputs explicit and audit-safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0025_research_output_types"
down_revision: str | None = "0024_all_features_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("status_suggestion_log")}
    if "output_type" not in existing:
        op.add_column(
            "status_suggestion_log",
            sa.Column("output_type", sa.String(length=24), nullable=False, server_default="信息沉淀"),
        )
    if "requires_human_confirmation" not in existing:
        op.add_column(
            "status_suggestion_log",
            sa.Column("requires_human_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "research_alerts" not in existing:
        op.add_column("status_suggestion_log", sa.Column("research_alerts", postgresql.JSONB()))
    if "hypothesis_health" not in existing:
        op.add_column("status_suggestion_log", sa.Column("hypothesis_health", postgresql.JSONB()))

    # Existing unapplied rows with a real status delta retain their original
    # behaviour after the upgrade; reminders and no-op records do not enter
    # the formal status-decision queue.
    bind.execute(
        sa.text(
            "UPDATE status_suggestion_log "
            "SET output_type = '状态变更建议', requires_human_confirmation = TRUE "
            "WHERE current_status <> suggested_status AND human_action IS NULL"
        )
    )


def downgrade() -> None:
    for name in ("hypothesis_health", "research_alerts", "requires_human_confirmation", "output_type"):
        op.drop_column("status_suggestion_log", name)
