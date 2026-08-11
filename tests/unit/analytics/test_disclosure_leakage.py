"""指标观测值的可得日期不得早于真实披露日。

这是窗口裁剪防未来信息泄露的前提：可得日填早了，系统会在数据还没公开时就用上它，
回测结论随之失真。

下面的实际披露日来自各公司定期报告原文（另一条独立于采集接口的路径）。曾经这里按
A 股法定截止日近似，37 个抽查期里有 7 个早于实际披露日，中芯国际与小鹏最严重
（分别提前 13 天与 28 天）——两家都习惯在截止日之后才发。
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.run_industry_case import (
    _HK_SECURITIES,
    _load_financials,
    _observation_date,
    _statutory_deadline,
)

# (证券代码, 报告期, 定期报告实际披露日)
ACTUAL_DISCLOSURE = [
    ("688981", "2024Q1", "2024-05-09"),
    ("688981", "2024Q3", "2024-11-07"),
    ("688981", "2025Q1", "2025-05-08"),
    ("688981", "2025Q3", "2025-11-13"),
    ("688981", "2025Q4", "2026-03-26"),
    ("688981", "2026Q1", "2026-05-14"),
    ("603986", "2024Q1", "2024-04-20"),
    ("603986", "2025Q1", "2025-04-26"),
    ("603986", "2025Q3", "2025-10-29"),
    ("603986", "2026Q1", "2026-04-30"),
    ("002371", "2024Q1", "2024-04-30"),
    ("002371", "2025Q4", "2026-04-18"),
    ("002371", "2026Q1", "2026-04-30"),
    ("600276", "2025Q4", "2026-03-25"),
    ("600276", "2026Q1", "2026-04-22"),
    ("603259", "2025Q4", "2026-03-23"),
    ("603259", "2026Q1", "2026-04-27"),
    ("000538", "2025Q4", "2026-03-31"),
    ("000538", "2026Q1", "2026-04-29"),
    ("002594", "2025Q2", "2025-08-29"),
    ("002594", "2025Q4", "2026-03-27"),
    ("002594", "2026Q1", "2026-04-28"),
    ("09868", "2025Q1", "2025-05-21"),
    ("09868", "2025Q2", "2025-08-19"),
    ("09868", "2026Q1", "2026-05-28"),
    ("00175", "2025Q2", "2025-08-14"),
    ("00175", "2025Q4", "2026-03-18"),
]


@pytest.fixture(scope="module")
def metric_rows() -> dict[tuple[str, str], dict]:
    financials = _load_financials()
    return {
        (security_id, row["period"]): row
        for security_id, rows in financials.items()
        for row in rows
    }


@pytest.mark.parametrize(("security_id", "period", "actual"), ACTUAL_DISCLOSURE)
def test_可得日期不早于实际披露日(
    security_id: str, period: str, actual: str, metric_rows: dict[tuple[str, str], dict]
) -> None:
    row = metric_rows.get((security_id, period))
    assert row is not None, f"{security_id} {period} 不在数据集里"

    available_on = _observation_date(
        period, row.get("disclosure_date"), is_hk=security_id in _HK_SECURITIES
    )
    assert available_on >= date.fromisoformat(actual), (
        f"{security_id} {period} 假定 {available_on} 可得，"
        f"实际 {actual} 才披露，提前了 {(date.fromisoformat(actual) - available_on).days} 天"
    )


def test_A股披露日已覆盖全部报告期() -> None:
    """A 股接口提供 NOTICE_DATE，不该退回兜底估计。

    覆盖率掉下来说明采集丢了字段，此时泄露判断会悄悄退化成按截止日近似。
    """
    financials = _load_financials()
    for security_id, rows in financials.items():
        if security_id in _HK_SECURITIES:
            continue
        missing = [r["period"] for r in rows if not r.get("disclosure_date")]
        assert not missing, f"{security_id} 缺披露日: {missing[:5]}"


def test_港股兜底晚于A股口径() -> None:
    """港股不强制季报，按 A 股季度截止日兜底会提前 20 天以上。"""
    for period in ("2025Q1", "2026Q1"):
        assert _statutory_deadline(period, is_hk=True) > _statutory_deadline(period)


def test_实际披露日优先于兜底估计() -> None:
    assert _observation_date("2025Q1", "2025-05-21") == date(2025, 5, 21)
    assert _observation_date("2025Q1", None) == _statutory_deadline("2025Q1")
