"""Persist Agent Runtime state and model usage.

Revision ID: 0011_ai_runtime_observability
Revises: 0010_pgvector_rag_pilot
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_ai_runtime_observability"
down_revision: str | None = "0010_pgvector_rag_pilot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_run",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), unique=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("model_version", sa.String(255)),
        sa.Column("prompt_version", sa.String(255)),
        sa.Column("retrieval_versions", postgresql.JSONB()),
        sa.Column("schema_name", sa.String(64)),
        sa.Column("degraded_reason", sa.String(128)),
        sa.Column("errors", postgresql.JSONB()),
        sa.Column("transitions", postgresql.JSONB()),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("verification", postgresql.JSONB()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ai_run_status_created", "ai_run", ["status", "created_at"])
    op.create_index("ix_ai_run_task_started", "ai_run", ["task", "started_at"])
    op.create_table(
        "model_call_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("ai_run.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(128)),
        sa.Column("prompt_version", sa.String(128)),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cost_amount", sa.Numeric(18, 8)),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("detail", postgresql.JSONB()),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_model_call_run", "model_call_log", ["run_id"])
    op.create_index("ix_model_call_model_time", "model_call_log", ["model_version", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_model_call_model_time", table_name="model_call_log")
    op.drop_index("ix_model_call_run", table_name="model_call_log")
    op.drop_table("model_call_log")
    op.drop_index("ix_ai_run_task_started", table_name="ai_run")
    op.drop_index("ix_ai_run_status_created", table_name="ai_run")
    op.drop_table("ai_run")
