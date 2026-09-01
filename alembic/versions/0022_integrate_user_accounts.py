"""Merge the deployed account branch with the application schema branch."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0022_integrate_user_accounts"
down_revision: tuple[str, str] = (
    "0021_thesis_maintenance_fields",
    "0017_user_accounts",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
