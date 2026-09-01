"""Separate market master data and add metric range semantics.

Revision ID: 0016_market_metric_bounds
Revises: 0015_company_metric_center
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_market_metric_bounds"
down_revision: str = "0015_company_metric_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_security",
        sa.Column("security_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="market"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("security_id"),
    )
    op.create_index("ix_market_security_name", "market_security", ["name"])
    op.create_index("ix_market_security_ticker", "market_security", ["ticker"])
    op.execute(
        """
        INSERT INTO market_security
            (security_id, name, ticker, industry, aliases, source)
        SELECT security_id, name, ticker, industry, aliases, 'maintained_backfill'
        FROM security
        ON CONFLICT (security_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_market_security_ticker", table_name="market_security")
    op.drop_index("ix_market_security_name", table_name="market_security")
    op.drop_table("market_security")
