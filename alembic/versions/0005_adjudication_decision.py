"""持久化独立导师裁决。"""

from alembic import op
import sqlalchemy as sa


revision = "0005_adjudication_decision"
down_revision = "0004_document_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "adjudication_decision",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("hypothesis", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(length=64), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    op.drop_table("adjudication_decision")
