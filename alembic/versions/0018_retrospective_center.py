"""Add governed retrospective drafts, source snapshots, and immutable versions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0018_retrospective_center"
down_revision = "0017_user_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrospective",
        sa.Column("retrospective_id", sa.String(96), primary_key=True),
        sa.Column(
            "thesis_id",
            sa.String(64),
            sa.ForeignKey("thesis.thesis_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("retrospective_type", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("reviewer", sa.String(64)),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("team", sa.String(64)),
        sa.Column("state", sa.String(16), nullable=False, server_default="草稿"),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completeness_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completeness_applicable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completeness_score", sa.Numeric(8, 6), nullable=False, server_default="0"),
        sa.Column("draft_content", postgresql.JSONB(), nullable=False),
        sa.Column("ai_candidate", postgresql.JSONB()),
        sa.Column("ai_run_id", sa.String(96)),
        sa.Column("ai_model_version", sa.String(128)),
        sa.Column("ai_prompt_version", sa.String(128)),
        sa.Column("ai_schema_version", sa.String(128)),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_retrospective_period_valid"),
        sa.CheckConstraint("lock_version >= 1", name="ck_retrospective_lock_positive"),
        sa.CheckConstraint("current_version >= 0", name="ck_retrospective_version_nonnegative"),
    )
    op.create_index(
        "uq_retrospective_scope",
        "retrospective",
        ["thesis_id", "retrospective_type", "period_start", "period_end"],
        unique=True,
        postgresql_where=sa.text("state <> '已归档'"),
    )
    op.create_index(
        "ix_retrospective_owner_state",
        "retrospective",
        ["owner", "state", "updated_at"],
    )
    op.create_index(
        "ix_retrospective_thesis_period",
        "retrospective",
        ["thesis_id", "period_end"],
    )

    op.create_table(
        "retrospective_source",
        sa.Column("source_id", sa.String(96), primary_key=True),
        sa.Column(
            "retrospective_id",
            sa.String(96),
            sa.ForeignKey("retrospective.retrospective_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(96), nullable=False),
        sa.Column("object_version", sa.String(96)),
        sa.Column("locator", sa.String(512)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("direction", sa.String(16)),
        sa.Column("strength", sa.String(16)),
        sa.Column("hypothesis_id", sa.String(64)),
        sa.Column("disclosed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("visibility_label", sa.String(32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "retrospective_id",
            "source_type",
            "object_id",
            "object_version",
            "locator",
            name="uq_retrospective_source_identity",
        ),
    )
    op.create_index(
        "ix_retrospective_source_report",
        "retrospective_source",
        ["retrospective_id", "source_type"],
    )

    op.create_table(
        "retrospective_version",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "retrospective_id",
            sa.String(96),
            sa.ForeignKey("retrospective.retrospective_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("published_by", sa.String(64), nullable=False),
        sa.Column("publish_reason", sa.Text(), nullable=False),
        sa.Column("ai_run_id", sa.String(96)),
        sa.Column("model_version", sa.String(128)),
        sa.Column("prompt_version", sa.String(128)),
        sa.Column("schema_version", sa.String(128)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("retrospective_id", "version", name="uq_retrospective_version"),
        sa.CheckConstraint("version >= 1", name="ck_retrospective_version_positive"),
    )


def downgrade() -> None:
    op.drop_table("retrospective_version")
    op.drop_index("ix_retrospective_source_report", table_name="retrospective_source")
    op.drop_table("retrospective_source")
    op.drop_index("ix_retrospective_thesis_period", table_name="retrospective")
    op.drop_index("ix_retrospective_owner_state", table_name="retrospective")
    op.drop_index("uq_retrospective_scope", table_name="retrospective")
    op.drop_table("retrospective")
