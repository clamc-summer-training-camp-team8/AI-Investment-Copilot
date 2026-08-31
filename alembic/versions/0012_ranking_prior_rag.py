"""Add versioned ranking priors for prior-aware RAG."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_ranking_prior_rag"
down_revision = "0011_ai_runtime_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranking_prior_snapshot",
        sa.Column("snapshot_id", sa.String(96), primary_key=True),
        sa.Column("security_id", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ranker_version", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("generator_model_version", sa.String(128)),
        sa.Column("judge_model_version", sa.String(128)),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False, server_default="generated"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("security_id", "direction", "horizon", "as_of", "ranker_version"),
    )
    op.create_index(
        "ix_ranking_prior_snapshot_scope",
        "ranking_prior_snapshot",
        ["security_id", "direction", "horizon", "status", "as_of"],
    )
    op.create_table(
        "ranking_prior_item",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "snapshot_id",
            sa.String(96),
            sa.ForeignKey("ranking_prior_snapshot.snapshot_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(192), nullable=False),
        sa.Column("base_rank", sa.Integer(), nullable=False),
        sa.Column("base_score", sa.Numeric(12, 8), nullable=False),
        sa.Column("judge_rank", sa.Integer()),
        sa.Column("judge_score", sa.Numeric(12, 8)),
        sa.Column("judge_confidence", sa.Numeric(12, 8)),
        sa.Column("final_rank", sa.Integer(), nullable=False),
        sa.Column("final_score", sa.Numeric(12, 8), nullable=False),
        sa.Column("feature_scores", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("citation_locators", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.UniqueConstraint("snapshot_id", "object_type", "object_id"),
    )
    op.create_index(
        "ix_ranking_prior_item_lookup",
        "ranking_prior_item",
        ["snapshot_id", "object_type", "object_id"],
    )
    op.create_index(
        "ix_ranking_prior_item_rank",
        "ranking_prior_item",
        ["snapshot_id", "object_type", "final_rank"],
    )


def downgrade() -> None:
    op.drop_table("ranking_prior_item")
    op.drop_table("ranking_prior_snapshot")
