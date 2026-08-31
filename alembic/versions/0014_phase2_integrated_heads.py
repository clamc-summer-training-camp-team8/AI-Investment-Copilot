"""Merge the Graph RAG, Agent, and ranking migration branches.

Revision ID: 0014_phase2_integrated_heads
Revises: 0013_one_thesis_per_security, 0013_seed_agent_metrics,
    0013_logic_topic_ranking
"""

from __future__ import annotations

from collections.abc import Sequence


revision: str = "0014_phase2_integrated_heads"
down_revision: tuple[str, str, str] = (
    "0013_one_thesis_per_security",
    "0013_seed_agent_metrics",
    "0013_logic_topic_ranking",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the three phase-2 branches without changing data."""


def downgrade() -> None:
    """Split back to the three phase-2 branch heads without changing data."""
