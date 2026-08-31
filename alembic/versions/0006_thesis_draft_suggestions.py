"""保存 AI 草稿的待采用建议。"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_thesis_draft_suggestions"
down_revision = "0005_adjudication_decision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "thesis",
        sa.Column(
            "draft_suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="AI 草稿建议候选；未经研究员采用不得进入正式配置",
        ),
    )


def downgrade() -> None:
    op.drop_column("thesis", "draft_suggestions")
