"""Seed the company metric-center dictionary.

Revision ID: 0015_company_metric_center
Revises: 0014_phase2_integrated_heads
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op
from app.services.company_metric_center import METRICS

revision: str = "0015_company_metric_center"
down_revision: str = "0014_phase2_integrated_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    metric = sa.table(
        "metric",
        sa.column("metric_id", sa.String), sa.column("version", sa.String),
        sa.column("name", sa.String), sa.column("category", sa.String),
        sa.column("definition", sa.Text), sa.column("unit", sa.String),
        sa.column("frequency", sa.String), sa.column("period_type", sa.String),
        sa.column("source_id", sa.String), sa.column("status", sa.String),
        sa.column("allow_yoy", sa.Boolean), sa.column("allow_qoq", sa.Boolean),
        sa.column("allow_peer", sa.Boolean),
    )
    rows = [{
        "metric_id": item.metric_id, "version": "v1.0", "name": item.name,
        "category": item.category, "definition": item.definition, "unit": item.unit,
        "frequency": item.frequency, "period_type": item.period_type,
        "source_id": item.source_id, "status": "已确认", "allow_yoy": True,
        "allow_qoq": True, "allow_peer": item.category in {"估值指标", "宏观及行业"},
    } for item in METRICS]
    op.get_bind().execute(
        insert(metric).values(rows).on_conflict_do_nothing(index_elements=["metric_id", "version"])
    )


def downgrade() -> None:
    ids = [item.metric_id for item in METRICS]
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM metric_observation WHERE metric_id = ANY(:ids)"), {"ids": ids})
    bind.execute(sa.text("DELETE FROM metric WHERE metric_id = ANY(:ids)"), {"ids": ids})
