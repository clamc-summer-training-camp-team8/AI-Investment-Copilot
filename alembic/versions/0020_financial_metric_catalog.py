"""Add the supplementary financial metrics used by the native Sina fallback."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op
from app.services.company_metric_center import METRICS

revision: str = "0020_financial_metric_catalog"
down_revision: str | None = "0019_backfill_market_sector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDS = {
    "FIN-RD-EXPENSE-CUM",
    "FIN-RD-RATIO",
    "FIN-INVENTORY-END",
    "FIN-RECEIVABLE-END",
    "FIN-CASH-END",
    "FIN-TOTAL-LIABILITIES",
}


def upgrade() -> None:
    metric = sa.table(
        "metric",
        sa.column("metric_id", sa.String),
        sa.column("version", sa.String),
        sa.column("name", sa.String),
        sa.column("category", sa.String),
        sa.column("definition", sa.Text),
        sa.column("unit", sa.String),
        sa.column("frequency", sa.String),
        sa.column("period_type", sa.String),
        sa.column("source_id", sa.String),
        sa.column("status", sa.String),
        sa.column("allow_yoy", sa.Boolean),
        sa.column("allow_qoq", sa.Boolean),
        sa.column("allow_peer", sa.Boolean),
    )
    rows = [
        {
            "metric_id": item.metric_id,
            "version": "v1.0",
            "name": item.name,
            "category": item.category,
            "definition": item.definition,
            "unit": item.unit,
            "frequency": item.frequency,
            "period_type": item.period_type,
            "source_id": item.source_id,
            "status": "已确认",
            "allow_yoy": True,
            "allow_qoq": True,
            "allow_peer": False,
        }
        for item in METRICS
        if item.metric_id in _IDS
    ]
    if rows:
        op.get_bind().execute(
            insert(metric).values(rows).on_conflict_do_nothing(
                index_elements=["metric_id", "version"]
            )
        )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM metric_observation WHERE metric_id = ANY(:ids)"),
        {"ids": list(_IDS)},
    )
    op.get_bind().execute(
        sa.text("DELETE FROM metric WHERE metric_id = ANY(:ids)"),
        {"ids": list(_IDS)},
    )
