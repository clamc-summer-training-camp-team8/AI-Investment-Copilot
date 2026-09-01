"""状态建议只产生建议，不改状态。

对应 PRD 5.4 与 FR-S-002：系统按证据、阈值和复核日生成状态建议，
不自动发布正式状态。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.calc.rules import (
    EvidenceSummary,
    check_invalidation,
    suggest_status,
    summarize_evidence,
)
from app.core.config import RuleThresholds
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)
from tests.conftest import make_observation


def test_未触发状态变化时仅信息沉淀(thresholds: RuleThresholds) -> None:
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [],
        [],
        thresholds=thresholds,
    )
    assert suggestion.output_type == "信息沉淀"
    assert suggestion.requires_human_confirmation is False


def test_建议携带理由与规则版本(thresholds: RuleThresholds) -> None:
    """人工确认时界面要展示依据，理由和版本都不能为空。"""
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=2, conflict_count=1)],
        [],
        thresholds=thresholds,
    )

    assert suggestion.suggested_status is ThesisStatus.DIVERGENT
    assert suggestion.reasons
    assert suggestion.triggered_hypotheses == ["H1"]
    assert suggestion.rule_version == thresholds.version
    assert suggestion.output_type == "状态变更建议"
    assert suggestion.requires_human_confirmation is True


def test_辅助假设的支持冲突并存不触发分歧(thresholds: RuleThresholds) -> None:
    """PRD 5.2 的分歧判定只看核心假设。"""
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H3", Importance.SUPPORTING, support_count=2, conflict_count=2)],
        [],
        thresholds=thresholds,
    )
    assert suggestion.suggested_status is ThesisStatus.VALIDATING


def test_重大风险优先于出现分歧(thresholds: RuleThresholds) -> None:
    breach = check_invalidation(
        "H2",
        [
            make_observation("2026Q1", date(2026, 3, 31), "0.10", expected="0.15"),
            make_observation("2026Q2", date(2026, 6, 30), "0.09", expected="0.15"),
        ],
        thesis_established_on=date(2026, 1, 15),
        threshold=Decimal("0.15"),
        direction=ExpectationDirection.HIGHER_BETTER,
        thresholds=thresholds,
    )
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=2, conflict_count=1)],
        [breach],
        thresholds=thresholds,
    )

    assert suggestion.suggested_status is ThesisStatus.MAJOR_RISK
    assert "H2" in suggestion.triggered_hypotheses
    assert suggestion.output_type == "状态变更建议"
    assert suggestion.requires_human_confirmation is True


def test_已关闭逻辑不再生成建议(thresholds: RuleThresholds) -> None:
    suggestion = suggest_status(
        ThesisStatus.CLOSED,
        [EvidenceSummary("H1", Importance.CORE, support_count=3, conflict_count=3)],
        [],
        thresholds=thresholds,
    )

    assert suggestion.suggested_status is ThesisStatus.CLOSED
    assert suggestion.requires_human_confirmation is False
    assert suggestion.output_type == "信息沉淀"


def test_只统计已确认证据() -> None:
    """待确认和已驳回的证据不参与状态计算（PRD 5.4 人工闸门）。"""
    summary = summarize_evidence(
        "H1",
        Importance.CORE,
        [
            (ImpactDirection.SUPPORT, ConfirmationStatus.CONFIRMED),
            (ImpactDirection.CONFLICT, ConfirmationStatus.PENDING),
            (ImpactDirection.CONFLICT, ConfirmationStatus.REJECTED),
        ],
    )

    assert summary.support_count == 1
    assert summary.conflict_count == 0


def test_支持证据沉淀为假设健康度而非状态待办(thresholds: RuleThresholds) -> None:
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [EvidenceSummary("H1", Importance.CORE, support_count=2, conflict_count=0)],
        [],
        thresholds=thresholds,
    )

    assert suggestion.output_type == "信息沉淀"
    assert suggestion.requires_human_confirmation is False
    assert suggestion.hypothesis_health[0].state == "强化"
    assert suggestion.hypothesis_health[0].support_count == 2


def test_到复核日追加提示(thresholds: RuleThresholds) -> None:
    suggestion = suggest_status(
        ThesisStatus.VALIDATING,
        [],
        [],
        thresholds=thresholds,
        next_review_at=date(2026, 8, 1),
        today=date(2026, 8, 8),
    )
    assert any("复核" in r for r in suggestion.reasons)
    assert suggestion.output_type == "研究提醒"
    assert suggestion.requires_human_confirmation is False
