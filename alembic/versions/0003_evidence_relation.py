"""拆分证据关联并回填历史单关联记录。"""

from alembic import op
import sqlalchemy as sa


revision = "0003_evidence_relation"
down_revision = "0002_evidence_detail_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_relation",
        sa.Column("relation_id", sa.String(length=64), primary_key=True),
        sa.Column("evidence_id", sa.String(length=64), sa.ForeignKey("evidence.evidence_id", ondelete="CASCADE"), nullable=False),
        sa.Column("thesis_id", sa.String(length=64), sa.ForeignKey("thesis.thesis_id", ondelete="CASCADE"), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=64), sa.ForeignKey("hypothesis.hypothesis_id"), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("strength", sa.String(length=16)),
        sa.Column("reason", sa.Text()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="待确认"),
        sa.Column("created_by", sa.String(length=64), nullable=False, server_default="migration"),
        sa.Column("reviewed_by", sa.String(length=64)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("deactivated_by", sa.String(length=64)),
        sa.Column("deactivated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_evidence_relation_evidence", "evidence_relation", ["evidence_id", "status"])
    op.create_index("ix_evidence_relation_thesis", "evidence_relation", ["thesis_id", "status"])
    # 保留旧字段以兼容历史接口，同时每条既有证据获得一条初始关联。
    op.execute(
        """
        INSERT INTO evidence_relation (
            relation_id, evidence_id, thesis_id, hypothesis_id, direction, strength,
            reason, status, created_by, reviewed_by, reviewed_at
        )
        SELECT
            'legacy-' || evidence_id, evidence_id, thesis_id, hypothesis_id, direction, strength,
            review_note, confirmation_status, COALESCE(confirmed_by, 'migration'), confirmed_by, confirmed_at
        FROM evidence
        """
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_relation_thesis", table_name="evidence_relation")
    op.drop_index("ix_evidence_relation_evidence", table_name="evidence_relation")
    op.drop_table("evidence_relation")
