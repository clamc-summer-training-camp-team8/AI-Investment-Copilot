"""Merge automatic collection with the phase-three feature graph."""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0024_all_features_heads"
down_revision: tuple[str, str] = (
    "0023_phase3_feature_heads",
    "0015_logic_change_consolidation",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
