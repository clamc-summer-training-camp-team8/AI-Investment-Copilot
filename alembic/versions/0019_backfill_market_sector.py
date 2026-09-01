"""Backfill market-sector links from the existing market security catalogue."""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0019_backfill_market_sector"
down_revision: str | None = "0018_coverage_universe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 市场表目前只有完整行业路径，先用一级行业作为稳定的市场板块名称；
    # 后续数据源同步可将 market_sector.code/description 替换成更细的官方板块字典。
    op.execute(
        """
        INSERT INTO market_sector (market_sector_id, name, source)
        SELECT 'MSEC-' || md5(board_name), board_name, 'market_security'
        FROM (
            SELECT COALESCE(NULLIF(split_part(industry, '-', 1), ''), '未分类') AS board_name
            FROM market_security
            GROUP BY 1
        ) boards
        ON CONFLICT (name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE market_security AS company
        SET market_sector_id = sector.market_sector_id
        FROM market_sector AS sector
        WHERE sector.name = COALESCE(NULLIF(split_part(company.industry, '-', 1), ''), '未分类')
          AND company.market_sector_id IS NULL
        """
    )


def downgrade() -> None:
    op.execute("UPDATE market_security SET market_sector_id = NULL")
    op.execute("DELETE FROM market_sector WHERE source = 'market_security'")
