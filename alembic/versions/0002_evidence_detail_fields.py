"""为证据详情增加可核验事实字段。

详情页依赖的摘录、来源和时间必须与证据一起持久化，不能在前端临时拼接。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_evidence_detail_fields"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("security_id", sa.String(length=64), nullable=True))
    op.add_column("evidence", sa.Column("fact_excerpt", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("source_document_id", sa.String(length=64), nullable=True))
    op.add_column("evidence", sa.Column("source_document_title", sa.String(length=512), nullable=True))
    op.add_column("evidence", sa.Column("disclosed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("evidence", sa.Column("occurred_at", sa.Date(), nullable=True))
    op.add_column("evidence", sa.Column("source_url", sa.String(length=2048), nullable=True))
    op.create_index("ix_evidence_security_id", "evidence", ["security_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evidence_security_id", table_name="evidence")
    op.drop_column("evidence", "source_url")
    op.drop_column("evidence", "occurred_at")
    op.drop_column("evidence", "disclosed_at")
    op.drop_column("evidence", "source_document_title")
    op.drop_column("evidence", "source_document_id")
    op.drop_column("evidence", "fact_excerpt")
    op.drop_column("evidence", "security_id")
