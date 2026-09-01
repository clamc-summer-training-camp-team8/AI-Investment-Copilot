"""Persist daily AI consolidation for a principal investment logic."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_logic_change_consolidation"
down_revision = "0014_phase2_integrated_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "logic_change_digest",
        sa.Column("digest_id", sa.String(96), primary_key=True),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False),
        sa.Column("thesis_id", sa.String(64), sa.ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("overall_direction", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("hypothesis_impacts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("open_questions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_document_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Numeric(6, 4)),
        sa.Column("ai_status", sa.String(16), nullable=False, server_default="候选"),
        sa.Column("confirmation_status", sa.String(16), nullable=False, server_default="待确认"),
        sa.Column("model_version", sa.String(128)),
        sa.Column("prompt_version", sa.String(128)),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("security_id", "thesis_id", "business_date"),
    )
    op.create_index(
        "ix_logic_change_digest_security_date",
        "logic_change_digest",
        ["security_id", "business_date"],
    )
    op.create_index(
        "ix_logic_change_digest_thesis_date",
        "logic_change_digest",
        ["thesis_id", "business_date"],
    )


def downgrade() -> None:
    op.drop_table("logic_change_digest")
