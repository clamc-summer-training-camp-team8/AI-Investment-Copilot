"""Research asset lineage, immutable revisions, runs, snapshots and search index."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_research_asset_layer"
down_revision = "0007_ingestion_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "source" not in tables:
        _create_asset_tables()
    _add_job_columns(inspector)
    _add_version_columns(inspector)
    _backfill_assets()


def _create_asset_tables() -> None:
    op.create_table(
        "source",
        sa.Column("source_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("authorization_status", sa.String(32), nullable=False, server_default="待确认"),
        sa.Column("base_url", sa.String(1024)),
        sa.Column("license_note", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "industry",
        sa.Column("industry_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("parent_id", sa.String(64), sa.ForeignKey("industry.industry_id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "security_industry_membership",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("security.security_id"), nullable=False),
        sa.Column("industry_id", sa.String(64), sa.ForeignKey("industry.industry_id"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("source.source_id")),
        sa.UniqueConstraint("security_id", "industry_id", "valid_from"),
    )
    op.create_index(
        "ix_security_industry_active", "security_industry_membership", ["security_id", "valid_to"]
    )
    op.create_table(
        "document_security_relation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(64), sa.ForeignKey("document.document_id"), nullable=False),
        sa.Column("security_id", sa.String(64), sa.ForeignKey("security.security_id"), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False, server_default="主体"),
        sa.Column("status", sa.String(16), nullable=False, server_default="已确认"),
        sa.Column("confidence", sa.Numeric(6, 4)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("document_id", "security_id", "relation_type"),
    )
    op.create_table(
        "document_revision",
        sa.Column("revision_id", sa.String(96), primary_key=True),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("canonical_document_id", sa.String(64), sa.ForeignKey("document.document_id")),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("object_key", sa.String(1024), unique=True),
        sa.Column("object_version_id", sa.String(255)),
        sa.Column("media_type", sa.String(128)),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("source.source_id")),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("authorization_status", sa.String(32), nullable=False, server_default="待确认"),
        sa.Column("uploaded_by", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_document_revision_document_id", "document_revision", ["document_id"])
    op.create_table(
        "ingestion_run",
        sa.Column("run_id", sa.String(96), primary_key=True),
        sa.Column("revision_id", sa.String(96), sa.ForeignKey("document_revision.revision_id"), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("chunker_version", sa.String(32), nullable=False),
        sa.Column("extractor_version", sa.String(32), nullable=False),
        sa.Column("embedding_version", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quality_summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ingestion_run_revision_status", "ingestion_run", ["revision_id", "status", "created_at"]
    )
    op.create_table(
        "ingestion_artifact",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(96), sa.ForeignKey("ingestion_run.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("artifact_key", sa.String(160), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "artifact_type", "artifact_key"),
    )
    op.create_table(
        "thesis_revision_draft",
        sa.Column("draft_id", sa.String(96), primary_key=True),
        sa.Column("thesis_id", sa.String(64), sa.ForeignKey("thesis.thesis_id"), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="editing"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_thesis_revision_owner", "thesis_revision_draft", ["owner", "status"])
    op.create_index(
        "uq_thesis_revision_editing",
        "thesis_revision_draft",
        ["thesis_id"],
        unique=True,
        postgresql_where=sa.text("status = 'editing'"),
    )
    op.create_table(
        "segment_search_index",
        sa.Column("index_id", sa.String(192), primary_key=True),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("document_segment.id", ondelete="CASCADE")),
        sa.Column("ingestion_run_id", sa.String(96), sa.ForeignKey("ingestion_run.run_id", ondelete="CASCADE")),
        sa.Column("document_id", sa.String(64), nullable=False, index=True),
        sa.Column("locator", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("visibility_label", sa.String(32), nullable=False),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_segment_search_vector", "segment_search_index", ["search_vector"], postgresql_using="gin")


def _add_job_columns(inspector) -> None:
    columns = {x["name"] for x in inspector.get_columns("document_processing_job")}
    additions = (
        sa.Column("revision_id", sa.String(96)),
        sa.Column("object_key", sa.String(1024)),
        sa.Column("object_version_id", sa.String(255)),
        sa.Column("upload_content_hash", sa.String(64)),
        sa.Column("ingestion_run_id", sa.String(96)),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("document_processing_job", column)
    op.alter_column("document_processing_job", "upload_path", existing_type=sa.String(1024), nullable=True)


def _add_version_columns(inspector) -> None:
    columns = {x["name"] for x in inspector.get_columns("thesis_version")}
    for column in (
        sa.Column("data_cutoff_at", sa.DateTime(timezone=True)),
        sa.Column("rule_version", sa.String(32)),
        sa.Column("model_versions", postgresql.JSONB()),
    ):
        if column.name not in columns:
            op.add_column("thesis_version", column)


def _backfill_assets() -> None:
    op.execute(
        """INSERT INTO source (source_id,name,source_type,authorization_status)
        VALUES ('SRC-USER-UPLOAD','用户上传','upload','用户授权上传'),
               ('SRC-LEGACY-URL','历史公开链接','public_url','待确认'),
               ('SRC-LEGACY-LOCAL','历史本地文件','local_file','待确认'),
               ('SRC-UNKNOWN','未知来源','unknown','待确认')
        ON CONFLICT (source_id) DO NOTHING"""
    )
    op.execute(
        """INSERT INTO industry (industry_id,name)
        SELECT 'IND-' || substr(md5(industry),1,24), industry FROM security
        WHERE industry IS NOT NULL AND btrim(industry) <> '' ON CONFLICT (name) DO NOTHING"""
    )
    op.execute(
        """INSERT INTO security_industry_membership (security_id,industry_id,valid_from,source_id)
        SELECT s.security_id,i.industry_id,DATE '1970-01-01','SRC-UNKNOWN'
        FROM security s JOIN industry i ON i.name=s.industry
        ON CONFLICT (security_id,industry_id,valid_from) DO NOTHING"""
    )
    op.execute(
        """INSERT INTO document_security_relation
        (document_id,security_id,relation_type,status,created_by)
        SELECT document_id,security_id,'主体','已确认','system-backfill' FROM document
        WHERE security_id IS NOT NULL ON CONFLICT (document_id,security_id,relation_type) DO NOTHING"""
    )
    op.execute(
        """INSERT INTO document_revision
        (revision_id,document_id,canonical_document_id,content_hash,source_filename,source_id,source_url,
         authorization_status,uploaded_by,published_at,created_at)
        SELECT 'DREV-' || substr(md5(d.content_hash),1,32),d.document_id,d.document_id,d.content_hash,
               coalesce(d.title,d.document_id),
               CASE WHEN d.raw_path LIKE 'http%' THEN 'SRC-LEGACY-URL'
                    WHEN d.raw_path IS NOT NULL THEN 'SRC-LEGACY-LOCAL' ELSE 'SRC-UNKNOWN' END,
               CASE WHEN d.raw_path LIKE 'http%' THEN d.raw_path ELSE NULL END,
               '待确认','system-backfill',d.published_at,d.ingested_at
        FROM document d ON CONFLICT (content_hash) DO NOTHING"""
    )
    op.execute(
        """INSERT INTO ingestion_run
        (run_id,revision_id,parser_version,chunker_version,extractor_version,status,
         segment_count,fact_count,event_count,quality_summary,started_at,finished_at,created_at)
        SELECT 'IRUN-BACKFILL-' || substr(md5(r.revision_id),1,24),r.revision_id,d.parser_version,
               'legacy-single-v1','event-v1','succeeded',
               (SELECT count(*) FROM document_segment s WHERE s.document_id=d.document_id),
               (SELECT count(*) FROM document_fact f WHERE f.document_id=d.document_id),
               (SELECT count(*) FROM event e WHERE e.document_id=d.document_id),
               jsonb_build_object('backfilled',true,'authorization_status',r.authorization_status),
               d.ingested_at,d.ingested_at,d.ingested_at
        FROM document_revision r JOIN document d ON d.document_id=r.canonical_document_id
        ON CONFLICT DO NOTHING"""
    )
    op.execute(
        """INSERT INTO ingestion_artifact (run_id,artifact_type,artifact_key,payload,content_hash)
        SELECT ir.run_id,'segment',s.locator,
               jsonb_build_object('locator',s.locator,'ordinal',s.ordinal,'content',s.content,'page',s.page,
                                  'content_kind',s.content_kind,'extraction_method',s.extraction_method),
               rpad(md5(s.content),64,'0')
        FROM ingestion_run ir JOIN document_revision r ON r.revision_id=ir.revision_id
        JOIN document_segment s ON s.document_id=r.canonical_document_id ON CONFLICT DO NOTHING"""
    )
    op.execute(
        """INSERT INTO segment_search_index
        (index_id,segment_id,document_id,locator,content,visibility_label,search_vector)
        SELECT 'legacy:' || s.id,s.id,s.document_id,s.locator,s.content,d.visibility_label,
               to_tsvector('simple',coalesce(s.content,''))
        FROM document_segment s JOIN document d ON d.document_id=s.document_id
        ON CONFLICT (index_id) DO UPDATE SET content=excluded.content,
        visibility_label=excluded.visibility_label,search_vector=excluded.search_vector,indexed_at=now()"""
    )


def downgrade() -> None:
    for name in ("model_versions", "rule_version", "data_cutoff_at"):
        op.drop_column("thesis_version", name)
    for name in ("ingestion_run_id", "upload_content_hash", "object_version_id", "object_key", "revision_id"):
        op.drop_column("document_processing_job", name)
    op.alter_column("document_processing_job", "upload_path", existing_type=sa.String(1024), nullable=False)
    for table in (
        "segment_search_index", "thesis_revision_draft", "ingestion_artifact", "ingestion_run",
        "document_revision", "document_security_relation", "security_industry_membership", "industry", "source",
    ):
        op.drop_table(table)
