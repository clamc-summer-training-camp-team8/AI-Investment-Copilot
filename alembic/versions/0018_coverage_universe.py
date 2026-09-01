"""Add market sector and local coverage directories."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op


revision: str = "0018_coverage_universe"
down_revision: str | None = "0017_metric_value_precision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_sector",
        sa.Column("market_sector_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="market"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("market_sector_id"),
        sa.UniqueConstraint("name", name="uq_market_sector_name"),
    )
    op.create_index("ix_market_sector_code", "market_sector", ["code"], unique=False)
    op.add_column(
        "market_security",
        sa.Column(
            "market_sector_id",
            sa.String(length=64),
            sa.ForeignKey("market_sector.market_sector_id"),
            nullable=True,
            comment="市场板块目录关联；由市场同步任务补全",
        ),
    )
    op.create_table(
        "coverage_sector",
        sa.Column("sector_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("sector_id"),
        sa.UniqueConstraint("name", name="uq_coverage_sector_name"),
    )
    op.create_table(
        "coverage_company",
        sa.Column("coverage_company_id", sa.String(length=64), nullable=False),
        sa.Column("sector_id", sa.String(length=64), nullable=False),
        sa.Column("security_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=True),
        sa.Column("industry", sa.String(length=128), nullable=True),
        sa.Column("market", sa.String(length=32), nullable=True),
        sa.Column("owner", sa.String(length=64), nullable=False, server_default="待分配"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="待建档"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["sector_id"], ["coverage_sector.sector_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["security_id"], ["security.security_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("coverage_company_id"),
        sa.UniqueConstraint("sector_id", "security_id", name="uq_coverage_company_sector_security"),
    )
    op.create_index("ix_coverage_company_sector", "coverage_company", ["sector_id"], unique=False)
    op.create_index("ix_coverage_company_security", "coverage_company", ["security_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_coverage_company_security", table_name="coverage_company")
    op.drop_index("ix_coverage_company_sector", table_name="coverage_company")
    op.drop_table("coverage_company")
    op.drop_table("coverage_sector")
    op.drop_column("market_security", "market_sector_id")
    op.drop_index("ix_market_sector_code", table_name="market_sector")
    op.drop_table("market_sector")
