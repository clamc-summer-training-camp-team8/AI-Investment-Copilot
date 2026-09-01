"""Allow large financial metric values such as market capitalization."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "0017_metric_value_precision"
down_revision: str | None = "0016_market_metric_bounds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VALUE_COLUMNS = (
    ("hypothesis_metric_map", "expected_value"),
    ("hypothesis_metric_map", "expected_lower"),
    ("hypothesis_metric_map", "expected_upper"),
    ("hypothesis_metric_map", "invalidation_threshold"),
    ("metric_observation", "actual_value"),
    ("metric_observation", "expected_value"),
    ("metric_observation", "benchmark_value"),
)


def upgrade() -> None:
    for table_name, column_name in _VALUE_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Numeric(precision=18, scale=6),
            type_=sa.Numeric(precision=30, scale=6),
        )


def downgrade() -> None:
    for table_name, column_name in _VALUE_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Numeric(precision=30, scale=6),
            type_=sa.Numeric(precision=18, scale=6),
        )
