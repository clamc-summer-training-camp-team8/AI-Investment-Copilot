"""共享夹具。

夹具中的业务数据一律来自 docs/data/数据分析交付包/业务样例包/ 或其派生，
且标记 is_illustrative。禁止引入真实投研资料。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.calc.deterministic import Observation
from app.core.config import RuleThresholds

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PACK_DIR = PROJECT_ROOT / "docs" / "data" / "数据分析交付包" / "业务样例包"


@pytest.fixture
def thresholds() -> RuleThresholds:
    """默认阈值。测试不依赖环境变量，避免本地 .env 影响断言结果。"""
    return RuleThresholds(
        version="rules-test",
        divergence_min_support=1,
        divergence_min_conflict=1,
        near_invalidation_ratio=0.1,
        consecutive_breach_periods=2,
        low_confidence_cutoff=0.6,
        trend_min_periods=4,
        trend_max_periods=8,
    )


@pytest.fixture
def sample_pack_dir() -> Path:
    return SAMPLE_PACK_DIR


def make_observation(
    period: str,
    observation_date: date,
    actual: str | None,
    *,
    metric_id: str = "MET-DEMO-001",
    expected: str | None = None,
    unit: str = "%",
    period_type: str = "单季度",
    metric_version: str = "v1.0",
) -> Observation:
    """构造观测值。数值用字符串传入并转 Decimal，避免测试里引入浮点残留。"""
    return Observation(
        metric_id=metric_id,
        period=period,
        observation_date=observation_date,
        actual_value=Decimal(actual) if actual is not None else None,
        unit=unit,
        period_type=period_type,
        expected_value=Decimal(expected) if expected is not None else None,
        metric_version=metric_version,
    )
