"""MVP 端到端闭环。

走完 PRD 13.1 定义的完整闭环：

```
资料输入 → 卡片草稿 → 人工发布 → 新资料关联 → 人工确认 → 状态复核 → 时间线
```

用真实样例包数据（`docs/data/数据分析交付包/业务样例包/`），不用数据库——编排
逻辑的正确性不依赖存储实现，仓储行为由 tests/integration/db 覆盖。

**最重要的断言**：跑完全流程后状态落在「关注」而不是「失效」。标注规范 §6 的
人工判断答案是「仅毛利率不达标 → 未满足全部条件 → 状态改为风险关注」。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.ai.gateway import Gateway
from app.core.config import RuleThresholds, settings
from app.core.domain import (
    DocumentSegmentRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ThesisRecord,
)
from app.core.domain import (
    MetricMappingRecord as Mapping,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)
from app.ingest.events import load_annotated_events
from app.ingest.parsers.text import parse_sample_pack
from app.ingest.segmentation import segment_document
from app.services import evidence as evidence_service
from app.services import status as status_service
from app.services import thesis as thesis_service
from app.services.permission import Actor
from app.workers import change_chain
from tests.fakes import build_fake_uow

THESIS_ID = "THS-DEMO-001"
SECURITY_ID = "DEMO001"
ESTABLISHED_ON = date(2026, 1, 15)
RESEARCHER = Actor(user_id="示例研究员", teams=frozenset({"权益研究"}))


@pytest.fixture
def sample_documents(sample_pack_dir):  # type: ignore[no-untyped-def]
    text = (sample_pack_dir / "样例投研资料.txt").read_text(encoding="utf-8")
    return dict(parse_sample_pack(text))


@pytest.fixture
def annotated_events(sample_pack_dir):  # type: ignore[no-untyped-def]
    return load_annotated_events(sample_pack_dir / "样例事件人工标注.csv")


def _current_event_segments(sample_documents, events):  # type: ignore[no-untyped-def]
    return [
        DocumentSegmentRecord(
            document_id=segment.document_id,
            locator=segment.locator,
            ordinal=segment.ordinal,
            content=segment.content,
        )
        for event in events
        for segment in segment_document(event.document_id, sample_documents[event.document_id])
    ]


def _seed_thesis(uow):  # type: ignore[no-untyped-def]
    """按台账建好 THS-DEMO-001 与三条核心假设、三条指标映射。

    H1/H2 要求连续两期，H3 单期即标记风险——期数逐条配置，不用全局默认值。
    """
    uow.thesis.add(
        ThesisRecord(
            thesis_id=THESIS_ID,
            security_id=SECURITY_ID,
            title="海外储能订单增长推动收入和利润改善",
            direction="看多",
            core_view="海外大型储能订单增长将在未来四个季度推动收入和利润改善",
            established_on=ESTABLISHED_ON,
            owner=RESEARCHER.user_id,
            status=ThesisStatus.VALIDATING,
            visibility="团队",
            team="权益研究",
            version=1,
            horizon_end_on=date(2027, 1, 15),
            next_review_at=date(2026, 7, 15),
            is_illustrative=True,
            # 台账的 thesis 级失效条件：海外收入连续两季低于预期 **且** 毛利率
            # 低于 18%。只有这两条假设参与，行业装机（H1）不在条件里。
            invalidation_require_all=True,
            invalidation_hypotheses=["HYP-DEMO-002", "HYP-DEMO-003"],
        )
    )

    specs = [
        (
            "HYP-DEMO-001",
            "海外大型储能装机需求保持增长",
            "行业",
            "MET-003",
            ExpectationDirection.HIGHER_BETTER,
            "0.00",
            2,
        ),
        (
            "HYP-DEMO-002",
            "新增海外订单能够按计划转化为收入",
            "经营",
            "MET-001",
            ExpectationDirection.HIGHER_BETTER,
            "0.15",
            2,
        ),
        (
            "HYP-DEMO-003",
            "海外项目毛利率不会显著下降",
            "盈利",
            "MET-002",
            ExpectationDirection.NOT_BELOW_THRESHOLD,
            "0.18",
            1,
        ),
    ]
    for hid, statement, htype, metric, direction, threshold, periods in specs:
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=hid,
                thesis_id=THESIS_ID,
                statement=statement,
                hypothesis_type=htype,
                importance=Importance.CORE,
            )
        )
        uow.thesis.add_mapping(
            Mapping(
                mapping_id=f"MAP-{hid}",
                hypothesis_id=hid,
                metric_id=metric,
                expected_direction=direction,
                expected_value=Decimal(threshold),
                invalidation_threshold=Decimal(threshold),
                invalidation_consecutive_periods=periods,
                expectation_source="研究员人工录入（样例）",
                confirmation_status=ConfirmationStatus.CONFIRMED,
            )
        )


def _seed_observations(uow):  # type: ignore[no-untyped-def]
    """按样例指标历史数据加载观测值。

    2026Q1：收入同比 0.18 达标（≥0.15），毛利率 0.17 不达标（<0.18）。
    2025Q2/Q3 收入低于预期，但早于建立日，必须被窗口裁剪排除。
    """
    rows = [
        ("MET-001", "2025Q2", date(2025, 6, 30), "0.11", "0.15"),
        ("MET-001", "2025Q3", date(2025, 9, 30), "0.13", "0.15"),
        ("MET-001", "2025Q4", date(2025, 12, 31), "0.16", "0.15"),
        ("MET-001", "2026Q1", date(2026, 3, 31), "0.18", "0.15"),
        ("MET-002", "2025Q4", date(2025, 12, 31), "0.19", "0.18"),
        ("MET-002", "2026Q1", date(2026, 3, 31), "0.17", "0.18"),
        ("MET-003", "2026Q1", date(2026, 3, 31), "0.12", "0.00"),
    ]
    for metric_id, period, obs_date, actual, expected in rows:
        uow.observations.add(
            ObservationRecord(
                security_id=SECURITY_ID,
                metric_id=metric_id,
                period=period,
                observation_date=obs_date,
                unit="%",
                actual_value=Decimal(actual),
                expected_value=Decimal(expected),
                data_version="market-demo-v1",
            )
        )


def test_闭环跑通且落在关注而非失效(
    thresholds: RuleThresholds, sample_documents, annotated_events
) -> None:  # type: ignore[no-untyped-def]
    """完整闭环：资料 → 候选证据 → 人工确认 → 状态建议 → 人工处置。"""
    uow = build_fake_uow()
    _seed_thesis(uow)
    _seed_observations(uow)

    # 事件的引用定位来自真实切片，不是编造的字符串
    locator_by_event: dict[str, str] = {}
    for event in annotated_events:
        parsed = sample_documents[event.document_id]
        segments = segment_document(event.document_id, parsed)
        locator_by_event[event.event_id] = segments[0].locator

    result = change_chain.process_events(
        uow,
        Gateway.build(settings),
        events=annotated_events,
        security_id=SECURITY_ID,
        actor=RESEARCHER,
        thresholds=thresholds,
        current_event_segments=_current_event_segments(sample_documents, annotated_events),
        locator_by_event=locator_by_event,
    )

    assert result.matched_theses == [THESIS_ID]
    assert len(result.candidates) == 4, "四条标注事件都应产出候选证据"

    # 候选证据一律待确认：worker 不能替人确认
    assert all(c.confirmation_status is ConfirmationStatus.PENDING for c in result.candidates)

    # 人工确认全部四条证据
    for candidate in result.candidates:
        evidence_service.handle(
            uow,
            evidence_id=candidate.evidence_id,
            action=evidence_service.CONFIRM,
            actor=RESEARCHER,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            thresholds=thresholds,
            note="样例确认",
        )

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        thresholds=thresholds,
    )

    # 核心断言：H2 支持与冲突并存 → 分歧；组合失效条件未满足 → 不是重大风险
    assert (
        suggestion.suggested_status is not ThesisStatus.MAJOR_RISK
    ), "仅毛利率不达标，AND 型失效条件未满足，不得判定失效（标注规范 §6）"
    assert suggestion.suggested_status is ThesisStatus.DIVERGENT
    assert "HYP-DEMO-002" in suggestion.triggered_hypotheses
    assert suggestion.requires_human_confirmation is True

    # 状态尚未变化：建议不自动生效
    assert uow.thesis.get(THESIS_ID).status is ThesisStatus.VALIDATING


def test_人工确认后状态才变更并生成版本与时间线(
    thresholds: RuleThresholds, sample_documents, annotated_events
) -> None:  # type: ignore[no-untyped-def]
    uow = build_fake_uow()
    _seed_thesis(uow)
    _seed_observations(uow)

    locator_by_event = {
        e.event_id: segment_document(e.document_id, sample_documents[e.document_id])[0].locator
        for e in annotated_events
    }
    change_chain.process_events(
        uow,
        Gateway.build(settings),
        events=annotated_events,
        security_id=SECURITY_ID,
        actor=RESEARCHER,
        thresholds=thresholds,
        current_event_segments=_current_event_segments(sample_documents, annotated_events),
        locator_by_event=locator_by_event,
    )
    for candidate in uow.evidence.list_for_thesis(THESIS_ID):
        evidence_service.handle(
            uow,
            evidence_id=candidate.evidence_id,
            action=evidence_service.CONFIRM,
            actor=RESEARCHER,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            thresholds=thresholds,
        )

    pending = uow.suggestions.list_for_thesis(THESIS_ID)[-1]
    assert pending.suggestion_id is not None

    updated = status_service.apply_decision(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        suggestion_id=pending.suggestion_id,
        action=status_service.ACCEPT,
        actor=RESEARCHER.user_id,
        reason="核心假设出现分歧，接受建议并安排复核",
    )

    assert updated.status is ThesisStatus.DIVERGENT
    assert uow.thesis.get(THESIS_ID).status is ThesisStatus.DIVERGENT

    versions = uow.versions.list_for_thesis(THESIS_ID)
    assert versions and versions[-1].triggered_by == "状态变更"
    assert versions[-1].change_reason

    actions = uow.audit.actions()  # type: ignore[attr-defined]
    for expected in ("确认", "状态变更", "生成状态建议", "生成候选证据"):
        assert expected in actions, f"审计缺少 {expected}"


def test_引用能回到原文段落(sample_documents, annotated_events) -> None:  # type: ignore[no-untyped-def]
    """FR-R-001：结果可纠错并保留原文。定位不准产品就没有可信度。"""
    for event in annotated_events:
        parsed = sample_documents[event.document_id]
        segments = segment_document(event.document_id, parsed)
        locator = segments[0].locator
        matched = [s for s in segments if s.locator == locator]
        assert matched, f"{locator} 无法回查"
        assert matched[0].content.strip()


def test_确认证据前状态计算不受待确认证据影响(
    thresholds: RuleThresholds, sample_documents, annotated_events
) -> None:  # type: ignore[no-untyped-def]
    """PRD 5.4 人工闸门：待确认证据不参与状态计算。"""
    uow = build_fake_uow()
    _seed_thesis(uow)
    _seed_observations(uow)

    locator_by_event = {
        e.event_id: segment_document(e.document_id, sample_documents[e.document_id])[0].locator
        for e in annotated_events
    }
    result = change_chain.process_events(
        uow,
        Gateway.build(settings),
        events=annotated_events,
        security_id=SECURITY_ID,
        actor=RESEARCHER,
        thresholds=thresholds,
        current_event_segments=_current_event_segments(sample_documents, annotated_events),
        locator_by_event=locator_by_event,
    )
    assert result.candidates

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        thresholds=thresholds,
    )
    # 四条证据全部待确认，分歧不成立
    assert suggestion.suggested_status is not ThesisStatus.DIVERGENT


def test_未发布逻辑不参与召回(thresholds: RuleThresholds) -> None:
    """草稿不应被新资料触发：未发布的逻辑还没进入监控。"""
    uow = build_fake_uow()
    _seed_thesis(uow)
    draft = uow.thesis.get(THESIS_ID)
    uow.thesis.update(ThesisRecord(**{**draft.__dict__, "status": ThesisStatus.DRAFT}))

    recalled = thesis_service.recall_candidates(uow, security_id=SECURITY_ID, actor=RESEARCHER)
    assert recalled == []


def test_窗口裁剪防止导入即误判(thresholds: RuleThresholds) -> None:
    """2025Q2/Q3 连续低于预期，但早于建立日，不得触发失效。"""
    uow = build_fake_uow()
    _seed_thesis(uow)
    _seed_observations(uow)

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        thresholds=thresholds,
    )
    assert suggestion.suggested_status is not ThesisStatus.MAJOR_RISK
    assert any("不判定失效" in r for r in suggestion.reasons)


def test_方向枚举不确定不得写入证据链(annotated_events) -> None:  # type: ignore[no-untyped-def]
    """基线里「不确定」在 ImpactDirection 没有对应值，必须转人工而不是当中性。"""
    from app.ingest.events import DirectionUnmappable, to_impact_direction

    assert to_impact_direction("削弱") is ImpactDirection.CONFLICT
    assert to_impact_direction("支持") is ImpactDirection.SUPPORT
    with pytest.raises(DirectionUnmappable):
        to_impact_direction("不确定")


def test_样例数据方向全部可映射(annotated_events) -> None:  # type: ignore[no-untyped-def]
    """样例标注的四条事件方向都应能落到正式枚举上。"""
    assert len(annotated_events) == 4
    assert all(not e.needs_human_review for e in annotated_events)
    directions = [e.impact_direction for e in annotated_events]
    assert directions.count(ImpactDirection.SUPPORT) == 1
    assert directions.count(ImpactDirection.CONFLICT) == 3


def test_未使用的映射类型别名保持一致() -> None:
    """MetricMappingRecord 与 Mapping 是同一个类型，避免引入两套值对象。"""
    assert MetricMappingRecord is Mapping


def test_失效条件只算参与的假设(thresholds: RuleThresholds) -> None:
    """收入与毛利率同时不达标时必须判失效，不能被无关假设压住。

    台账的失效条件只写了这两条。如果把长期达标的 H1（行业装机）也算进 AND，
    H1 永远达标就会永久压住失效判定，失效条件等于失灵。
    """
    uow = build_fake_uow()
    _seed_thesis(uow)

    # H1 达标；H2 连续两期低于 15%；H3 单期低于 18%
    rows = [
        ("MET-003", "2026Q1", date(2026, 3, 31), "0.12", "0.00"),
        ("MET-001", "2026Q1", date(2026, 3, 31), "0.10", "0.15"),
        ("MET-001", "2026Q2", date(2026, 6, 30), "0.09", "0.15"),
        ("MET-002", "2026Q2", date(2026, 6, 30), "0.17", "0.18"),
    ]
    for metric_id, period, obs_date, actual, expected in rows:
        uow.observations.add(
            ObservationRecord(
                security_id=SECURITY_ID,
                metric_id=metric_id,
                period=period,
                observation_date=obs_date,
                unit="%",
                actual_value=Decimal(actual),
                expected_value=Decimal(expected),
            )
        )

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        thresholds=thresholds,
    )

    assert suggestion.suggested_status is ThesisStatus.MAJOR_RISK
    assert {"HYP-DEMO-002", "HYP-DEMO-003"} <= set(suggestion.triggered_hypotheses)
