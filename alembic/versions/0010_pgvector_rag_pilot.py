"""Add versioned pgvector embeddings for the P1 hybrid-retrieval pilot."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


revision = "0010_pgvector_rag_pilot"
down_revision = "0009_asset_lifecycle_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "segment_embedding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "index_id",
            sa.String(192),
            sa.ForeignKey("segment_search_index.index_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_run_id",
            sa.String(96),
            sa.ForeignKey("ingestion_run.run_id", ondelete="CASCADE"),
        ),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("locator", sa.String(160), nullable=False),
        sa.Column("embedding_version", sa.String(64), nullable=False),
        sa.Column("embedding", VECTOR(256), nullable=False),
        sa.Column(
            "embedded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("index_id", "embedding_version"),
    )
    op.create_index("ix_segment_embedding_document_id", "segment_embedding", ["document_id"])
    op.create_index(
        "ix_segment_embedding_run_version",
        "segment_embedding",
        ["ingestion_run_id", "embedding_version"],
    )
    op.create_index(
        "ix_segment_embedding_hnsw_cosine",
        "segment_embedding",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("segment_embedding")
    op.execute("DROP EXTENSION IF EXISTS vector")
