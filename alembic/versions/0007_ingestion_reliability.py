"""持久化资料任务、统一复核队列与精确引用元数据。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_ingestion_reliability"
down_revision = "0006_thesis_draft_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    segment_columns = {item["name"] for item in inspector.get_columns("document_segment")}
    segment_additions = (
        sa.Column("content_kind", sa.String(16), nullable=False, server_default="paragraph"),
        sa.Column("extraction_method", sa.String(16), nullable=False, server_default="native"),
        sa.Column("table_index", sa.Integer()),
        sa.Column("row_index", sa.Integer()),
        sa.Column("cell_range", sa.String(64)),
        sa.Column("confidence", sa.Numeric(6, 4)),
    )
    for column in segment_additions:
        if column.name not in segment_columns:
            op.add_column("document_segment", column)

    existing_tables = set(inspector.get_table_names())
    if "document_processing_job" not in existing_tables:
        _create_processing_job()
    if "ingestion_review" not in existing_tables:
        _create_ingestion_review()


def _create_processing_job() -> None:
    op.create_table(
        "document_processing_job",
        sa.Column("job_id", sa.String(96), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("actor_teams", postgresql.JSONB(), nullable=False),
        sa.Column("upload_path", sa.String(1024), nullable=False),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("security_id", sa.String(64)),
        sa.Column("thesis_id", sa.String(64)),
        sa.Column("view", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("attempt_count >= 1", name="document_job_attempt_positive"),
    )
    op.create_index("ix_document_processing_job_document_id", "document_processing_job", ["document_id"])
    op.create_index("ix_document_processing_job_owner", "document_processing_job", ["owner"])
    op.create_index(
        "ix_document_job_owner_status",
        "document_processing_job",
        ["owner", "status", "created_at"],
    )


def _create_ingestion_review() -> None:
    op.create_table(
        "ingestion_review",
        sa.Column("review_id", sa.String(96), primary_key=True),
        sa.Column("dedupe_key", sa.String(160), nullable=False, unique=True),
        sa.Column("review_type", sa.String(32), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("job_id", sa.String(96)),
        sa.Column("event_id", sa.String(64)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assignee", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "security_candidates",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("resolution", sa.Text()),
        sa.Column("resolved_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_ingestion_review_document_id", "ingestion_review", ["document_id"])
    op.create_index(
        "ix_ingestion_review_queue", "ingestion_review", ["assignee", "status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("ingestion_review")
    op.drop_table("document_processing_job")
    for column in (
        "confidence",
        "cell_range",
        "row_index",
        "table_index",
        "extraction_method",
        "content_kind",
    ):
        op.drop_column("document_segment", column)
