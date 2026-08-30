"""Enforce one currently maintained investment thesis per security.

Revision ID: 0013_one_thesis_per_security
Revises: 0012_evidence_retrieval_trace

Existing quarterly/research drafts are retained as read-only history.  The most recently
updated/established row becomes the current company thesis; older rows point to it through
``superseded_by_thesis_id``.  No hypothesis, evidence, review task or immutable version is
deleted or rewired.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_one_thesis_per_security"
down_revision: str | None = "0012_evidence_retrieval_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column(
        "thesis",
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="同一公司仅一条当前维护逻辑；历史行只读保留",
        ),
    )
    op.add_column(
        "thesis",
        sa.Column(
            "superseded_by_thesis_id",
            sa.String(length=64),
            nullable=True,
            comment="历史逻辑归并到的当前公司级逻辑",
        ),
    )
    op.create_foreign_key(
        "fk_thesis_superseded_by_thesis_id_thesis",
        "thesis",
        "thesis",
        ["superseded_by_thesis_id"],
        ["thesis_id"],
    )
    ranked = connection.execute(
        sa.text(
            """
            SELECT thesis_id, security_id,
                   first_value(thesis_id) OVER (
                       PARTITION BY security_id
                       ORDER BY updated_at DESC, established_on DESC, created_at DESC, thesis_id
                   ) AS canonical_id
            FROM thesis
            """
        )
    ).all()
    for thesis_id, _security_id, canonical_id in ranked:
        if thesis_id == canonical_id:
            continue
        connection.execute(
            sa.text(
                "UPDATE thesis SET is_current=false, superseded_by_thesis_id=:canonical "
                "WHERE thesis_id=:thesis_id"
            ),
            {"canonical": canonical_id, "thesis_id": thesis_id},
        )
    op.create_index(
        "uq_thesis_current_security_id",
        "thesis",
        ["security_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.alter_column("thesis", "is_current", server_default=None)


def downgrade() -> None:
    op.drop_index("uq_thesis_current_security_id", table_name="thesis")
    op.drop_constraint("fk_thesis_superseded_by_thesis_id_thesis", "thesis", type_="foreignkey")
    op.drop_column("thesis", "superseded_by_thesis_id")
    op.drop_column("thesis", "is_current")
