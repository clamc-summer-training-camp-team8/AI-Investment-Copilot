"""Add explicit content/auth governance and append-only source revision links."""

from alembic import op
import sqlalchemy as sa


revision = "0015_data_asset_governance"
down_revision = "0014_phase2_integrated_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "content_status",
            sa.String(24),
            nullable=False,
            server_default="待核验",
            comment="标题索引不得冒充完整正文",
        ),
    )
    for table in ("source", "document_revision"):
        op.add_column(table, sa.Column("authorization_basis", sa.Text()))
        op.add_column(table, sa.Column("authorization_verified_by", sa.String(64)))
        op.add_column(table, sa.Column("authorization_verified_at", sa.DateTime(timezone=True)))
    op.add_column(
        "document_revision",
        sa.Column("content_status", sa.String(24), nullable=False, server_default="待核验"),
    )

    # 一份不可变原件可以被多个公告索引或上传记录引用。去重键应位于“文档 + 内容”维度，
    # 对象键也允许被多条 revision 共享，物理对象本身仍按 SHA-256 寻址且不可变。
    op.drop_constraint("uq_document_revision_content_hash", "document_revision", type_="unique")
    op.drop_constraint("uq_document_revision_object_key", "document_revision", type_="unique")
    op.create_unique_constraint(
        "uq_document_revision_document_content",
        "document_revision",
        ["canonical_document_id", "content_hash"],
    )
    op.create_index(
        "ix_document_revision_content_hash", "document_revision", ["content_hash"]
    )
    op.create_index("ix_document_revision_object_key", "document_revision", ["object_key"])

    op.execute(
        """UPDATE document
           SET content_status = CASE
             WHEN parser_version='cninfo-announcement-v2' THEN '标题索引'
             WHEN is_illustrative THEN '合成样例'
             WHEN body IS NOT NULL AND btrim(body)<>'' THEN '完整正文'
             ELSE '待核验' END"""
    )
    op.execute(
        """UPDATE document_revision r
           SET content_status = CASE
             WHEN r.object_key IS NOT NULL THEN '原件已归档'
             WHEN d.parser_version='cninfo-announcement-v2' THEN '标题索引'
             WHEN d.is_illustrative THEN '合成样例'
             WHEN d.body IS NOT NULL AND btrim(d.body)<>'' THEN '完整正文'
             ELSE '待核验' END
           FROM document d WHERE d.document_id=r.canonical_document_id"""
    )
    op.execute(
        """UPDATE document_segment s
           SET content_kind='title_index', extraction_method='metadata'
           FROM document d
           WHERE d.document_id=s.document_id
             AND d.content_status='标题索引'"""
    )
    op.execute(
        """UPDATE document SET body=NULL WHERE content_status='标题索引'"""
    )
    op.execute(
        """UPDATE evidence e
           SET fact_excerpt=regexp_replace(
                 e.fact_excerpt,'^公告标题：','公告标题（非正文）：')
           FROM document d
           WHERE d.document_id=e.source_document_id
             AND d.content_status='标题索引'
             AND e.fact_excerpt LIKE '公告标题：%'"""
    )


def downgrade() -> None:
    op.drop_index("ix_document_revision_object_key", table_name="document_revision")
    op.drop_index("ix_document_revision_content_hash", table_name="document_revision")
    op.drop_constraint(
        "uq_document_revision_document_content", "document_revision", type_="unique"
    )
    op.create_unique_constraint(
        "uq_document_revision_content_hash", "document_revision", ["content_hash"]
    )
    op.create_unique_constraint("uq_document_revision_object_key", "document_revision", ["object_key"])
    op.drop_column("document_revision", "content_status")
    for table in ("document_revision", "source"):
        op.drop_column(table, "authorization_verified_at")
        op.drop_column(table, "authorization_verified_by")
        op.drop_column(table, "authorization_basis")
    op.drop_column("document", "content_status")
