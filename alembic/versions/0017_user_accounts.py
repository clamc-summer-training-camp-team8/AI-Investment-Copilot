"""Persist local user accounts used by the deployed authentication service.

Revision ID: 0017_user_accounts
Revises: 0014_phase2_integrated_heads
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_user_accounts"
down_revision: str = "0014_phase2_integrated_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("teams", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("document_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_account"),
    )


def downgrade() -> None:
    op.drop_table("user_account")
