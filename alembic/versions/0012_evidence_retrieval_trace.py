"""Persist evidence-level dual-route retrieval traces.

Revision ID: 0012_evidence_retrieval_trace
Revises: 0011_ai_runtime_observability
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_evidence_retrieval_trace"
down_revision: str | None = "0011_ai_runtime_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence",
        sa.Column("retrieval_trace", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence", "retrieval_trace")
