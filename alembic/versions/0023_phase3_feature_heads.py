"""Merge company research and retrospective migration heads."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0023_phase3_feature_heads"
down_revision: tuple[str, str] = (
    "0022_integrate_user_accounts",
    "0018_retrospective_center",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
