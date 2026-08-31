"""持久化正文抽取事实。"""

from alembic import op
import sqlalchemy as sa


revision = "0004_document_facts"
down_revision = "0003_evidence_relation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_fact",
        sa.Column("fact_id", sa.String(length=96), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=64),
            sa.ForeignKey("document.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locator", sa.String(length=128), nullable=False),
        sa.Column("fact_type", sa.String(length=32), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("change_rate_low", sa.Numeric(precision=12, scale=6)),
        sa.Column("change_rate_high", sa.Numeric(precision=12, scale=6)),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("extraction_version", sa.String(length=32), nullable=False),
        sa.UniqueConstraint(
            "document_id",
            "locator",
            "fact_type",
            "metric_name",
            name="uq_document_fact_document_id",
        ),
    )
    op.create_index(
        "ix_document_fact_document", "document_fact", ["document_id", "fact_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_document_fact_document", table_name="document_fact")
    op.drop_table("document_fact")
