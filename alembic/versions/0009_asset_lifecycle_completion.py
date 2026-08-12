"""Complete P0-3 asset lifecycle, deletion tombstones and historical lineage."""

from alembic import op
import sqlalchemy as sa


revision = "0009_asset_lifecycle_completion"
down_revision = "0008_research_asset_layer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_document_active", "document", ["deleted_at"])
    op.add_column(
        "document_revision", sa.Column("tombstoned_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_document_revision_tombstoned", "document_revision", ["tombstoned_at"]
    )
    _backfill_derived_lineage()


def _backfill_derived_lineage() -> None:
    op.execute(
        """INSERT INTO ingestion_artifact
        (run_id,artifact_type,artifact_key,payload,content_hash)
        SELECT ir.run_id,'fact',f.fact_id,
               jsonb_build_object(
                 'fact_id',f.fact_id,'document_id',f.document_id,'locator',f.locator,
                 'fact_type',f.fact_type,'metric_name',f.metric_name,'direction',f.direction,
                 'change_rate_low',f.change_rate_low,'change_rate_high',f.change_rate_high,
                 'raw_text',f.raw_text,'extraction_version',f.extraction_version),
               rpad(md5(f.raw_text),64,'0')
        FROM ingestion_run ir
        JOIN document_revision r ON r.revision_id=ir.revision_id
        JOIN document_fact f ON f.document_id=r.canonical_document_id
        ON CONFLICT DO NOTHING"""
    )
    op.execute(
        """INSERT INTO ingestion_artifact
        (run_id,artifact_type,artifact_key,payload,content_hash)
        SELECT ir.run_id,'event',e.event_id,
               jsonb_build_object(
                 'event_id',e.event_id,'document_id',e.document_id,'security_id',e.security_id,
                 'event_type',e.event_type,'summary',e.summary,'occurred_on',e.occurred_on,
                 'disclosure_time',e.disclosure_time,'fingerprint',e.fingerprint,
                 'source_document_ids',e.source_document_ids,'version',e.version),
               rpad(md5(e.fingerprint),64,'0')
        FROM ingestion_run ir
        JOIN document_revision r ON r.revision_id=ir.revision_id
        JOIN event e ON e.document_id=r.canonical_document_id
        ON CONFLICT DO NOTHING"""
    )


def downgrade() -> None:
    op.drop_index("ix_document_revision_tombstoned", table_name="document_revision")
    op.drop_column("document_revision", "tombstoned_at")
    op.drop_index("ix_document_active", table_name="document")
    op.drop_column("document", "deleted_at")
