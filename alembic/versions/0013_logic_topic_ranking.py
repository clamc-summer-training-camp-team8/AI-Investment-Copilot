"""Add normalized investment logic topics and traceable relations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_logic_topic_ranking"
down_revision = "0012_ranking_prior_rag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "logic_topic",
        sa.Column("topic_id", sa.String(96), primary_key=True),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("security.security_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("normalized_statement", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("topic_version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("source_thesis_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("security_id", "normalized_statement", "direction", "horizon", "topic_version"),
    )
    op.create_index("ix_logic_topic_scope", "logic_topic", ["security_id", "direction", "horizon", "status"])
    op.create_table(
        "logic_topic_relation",
        sa.Column("relation_id", sa.String(96), primary_key=True),
        sa.Column("topic_id", sa.String(96), sa.ForeignKey("logic_topic.topic_id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(255), nullable=False),
        sa.Column("relation", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 6), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("citation_locators", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("valid_from", sa.DateTime(timezone=True)),
        sa.Column("valid_to", sa.DateTime(timezone=True)),
        sa.Column("model_version", sa.String(128)),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("topic_id", "object_type", "object_id", "relation"),
    )
    op.create_index("ix_logic_topic_relation_topic", "logic_topic_relation", ["topic_id", "object_type", "status"])


def downgrade() -> None:
    op.drop_table("logic_topic_relation")
    op.drop_table("logic_topic")
