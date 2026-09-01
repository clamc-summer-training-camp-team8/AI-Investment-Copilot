"""Backfill hypothesis health state from historical status suggestions."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0027_hyp_health_backfill"
down_revision: str | None = "0026_hypothesis_health_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (thesis_id)
                    thesis_id,
                    hypothesis_health,
                    created_at
                FROM status_suggestion_log
                WHERE hypothesis_health IS NOT NULL
                  AND jsonb_typeof(hypothesis_health) = 'array'
                  AND jsonb_array_length(hypothesis_health) > 0
                ORDER BY thesis_id, created_at DESC, id DESC
            ),
            expanded AS (
                SELECT
                    latest.thesis_id,
                    latest.created_at,
                    item AS health
                FROM latest, jsonb_array_elements(latest.hypothesis_health) AS item
            )
            UPDATE hypothesis AS h
            SET
                health_state = expanded.health ->> 'state',
                health_reason = expanded.health ->> 'reason',
                health_support_count = COALESCE(NULLIF(expanded.health ->> 'support_count', '')::integer, 0),
                health_conflict_count = COALESCE(NULLIF(expanded.health ->> 'conflict_count', '')::integer, 0),
                health_updated_at = expanded.created_at
            FROM expanded
            WHERE h.thesis_id = expanded.thesis_id
              AND h.hypothesis_id = expanded.health ->> 'hypothesis_id'
            """
        )
    )


def downgrade() -> None:
    # Data-only backfill; schema remains owned by 0026.
    pass
