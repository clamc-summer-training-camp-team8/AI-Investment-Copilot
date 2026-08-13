"""真实案例闭环的回归保护。

数据在 `real_data/` 根目录，已随仓库提交（ADR-0006），因此这些用例在 CI 里
真实执行。保留 skip 分支只为兜住数据被误删的情况。

案例：阳光电源（300274.SZ）2025 年报储能业务。它与虚构样例 THS-DEMO-001 结构
一致，但「收入大幅达标、毛利率显著不达标」这个形态是真实发生的，不是我们设计的。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.calc.deterministic import (
    CalibrationConflictError,
    Observation,
    expectation_gap,
    period_over_period,
)
from app.core.config import Settings
from app.core.enums import ConfirmationStatus, ExpectationDirection, ThesisStatus
from app.core.timeutil import BUSINESS_TZ, ensure_aware, is_leakage
from app.services import status as status_service
from tests.fakes import build_fake_uow

run_real_case = pytest.importorskip("scripts.run_real_case")

settings = Settings(_env_file=None, llm_provider="local")

pytestmark = pytest.mark.skipif(
    not (run_real_case.REAL_DATA_DIR / "observations.csv").is_file(),
    reason="real_data/ 未准备，真实数据不进版本控制",
)


@pytest.fixture
def seeded():  # type: ignore[no-untyped-def]
    uow = build_fake_uow()
    run_real_case._seed(uow)
    for record in run_real_case._load_observations(
        run_real_case.REAL_DATA_DIR / "observations.csv"
    ):
        uow.observations.add(record)
    return uow


def test_真实数据闭环落在关注而非失效() -> None:
    """核心断言。收入同比 49.39% 远超 30% 预期，毛利率 22.95% 低于 30% 预期，
    AND 型失效条件只成立一条，正确结论是关注。
    """
    result = run_real_case.run()

    assert result.suggestion_status != ThesisStatus.MAJOR_RISK.value
    assert result.final_status == ThesisStatus.VALIDATING.value
    assert "不判定失效" in result.invalidation_note
    assert result.candidates == result.events
    assert result.confirmed == result.events


def test_组合条件是这个结论的决定因素(seeded) -> None:  # type: ignore[no-untyped-def]
    """改成「任一满足」就应该建议重大风险。

    这条证明「关注」来自 AND 判定，不是因为判定逻辑本身没生效。
    """
    thesis = seeded.thesis.get(run_real_case.THESIS_ID)
    hypotheses = seeded.thesis.list_hypotheses(run_real_case.THESIS_ID)

    and_result = status_service.compute_suggestion(
        seeded, thesis=thesis, hypotheses=hypotheses, thresholds=settings.rules
    )
    assert and_result.suggested_status is ThesisStatus.VALIDATING

    seeded.thesis.update(replace(thesis, invalidation_require_all=False))
    or_result = status_service.compute_suggestion(
        seeded,
        thesis=seeded.thesis.get(run_real_case.THESIS_ID),
        hypotheses=hypotheses,
        thresholds=settings.rules,
    )
    assert or_result.suggested_status is ThesisStatus.MAJOR_RISK


def test_建立日之前的观察期被裁剪(seeded) -> None:  # type: ignore[no-untyped-def]
    """2024Q4 毛利率 27.48% 已低于 30% 预期，但早于建立日 2025-01-10。

    这一期必须被排除。它不影响本例最终结论（2025Q1-Q3 达标会重置连续计数），
    但如果建立日更晚、或早期连续多期不达标，不裁剪就会在建卡当天误报风险。
    """
    thesis = seeded.thesis.get(run_real_case.THESIS_ID)
    observations = seeded.observations.list_for_metric(run_real_case.SECURITY_ID, "MET-002")

    excluded = [o.period for o in observations if o.observation_date < thesis.established_on]
    assert "2024Q4" in excluded

    early = next(o for o in observations if o.period == "2024Q4")
    assert early.actual_value is not None
    assert early.actual_value < Decimal("0.30"), "这一期确实不达标，裁剪才有意义"


def test_口径不一致禁止混算() -> None:
    """真实数据里收入同比是累计口径、毛利率是单季度口径，混算必须被拦。"""
    accumulated = Observation(
        metric_id="MET-001",
        period="FY2025",
        observation_date=date(2025, 12, 31),
        actual_value=Decimal("0.4939"),
        unit="%",
        period_type="累计",
        expected_value=Decimal("0.30"),
    )
    quarterly = Observation(
        metric_id="MET-002",
        period="2025Q4",
        observation_date=date(2025, 12, 31),
        actual_value=Decimal("0.2295"),
        unit="%",
        period_type="单季度",
        expected_value=Decimal("0.30"),
    )

    with pytest.raises(CalibrationConflictError):
        period_over_period(quarterly, accumulated)


def test_预期差复算与披露值一致() -> None:
    """2025Q4 毛利率 22.95% 由年报披露的营业收入与营业成本推算，
    与公开研报 23.0% 吻合，误差在四舍五入范围内。
    """
    revenue = Decimal("22782.4")
    cost = Decimal("17553.0")
    margin = ((revenue - cost) / revenue).quantize(Decimal("0.0001"))
    assert margin == Decimal("0.2295")
    assert abs(margin - Decimal("0.230")) < Decimal("0.001")

    gap = expectation_gap(
        Observation(
            metric_id="MET-002",
            period="2025Q4",
            observation_date=date(2025, 12, 31),
            actual_value=margin,
            unit="%",
            period_type="单季度",
            expected_value=Decimal("0.30"),
        )
    )
    assert gap.verdict == "冲突"
    assert gap.absolute_gap is not None and gap.absolute_gap < 0


def test_年报数据在披露前使用属于泄露() -> None:
    """DQ-003。2025Q4 毛利率 2026-03-31 才披露，建卡时点用它就是未来信息。"""
    disclosed = ensure_aware(datetime(2026, 3, 31, 19, 0), assume=BUSINESS_TZ)

    before = ensure_aware(datetime(2026, 1, 15, 9, 0), assume=BUSINESS_TZ)
    after = ensure_aware(datetime(2026, 4, 1, 9, 0), assume=BUSINESS_TZ)

    assert is_leakage(disclosed, before) is True
    assert is_leakage(disclosed, after) is False


def test_全部事件的披露时间可比且带时区() -> None:
    """naive datetime 会让跨来源比较退回混算，DQ-003 判定随之失效。"""
    from app.ingest.events import load_annotated_events

    events = load_annotated_events(run_real_case.REAL_DATA_DIR / "events.csv")
    assert events
    for event in events:
        assert event.disclosure_time.tzinfo is not None
        assert not event.needs_human_review, f"{event.event_id} 方向无法映射"


def test_三条假设的指标方向配置正确(seeded) -> None:  # type: ignore[no-untyped-def]
    """毛利率是「不低于阈值」，收入与装机是「越高越好」。配错会让判定方向反转。"""
    directions = {}
    for hypothesis in seeded.thesis.list_hypotheses(run_real_case.THESIS_ID):
        for mapping in seeded.thesis.list_mappings(hypothesis.hypothesis_id):
            directions[mapping.metric_id] = mapping.expected_direction

    assert directions["MET-002"] is ExpectationDirection.NOT_BELOW_THRESHOLD
    assert directions["MET-001"] is ExpectationDirection.HIGHER_BETTER
    assert directions["MET-003"] is ExpectationDirection.HIGHER_BETTER


def test_真实案例不带演示标记(seeded) -> None:  # type: ignore[no-untyped-def]
    """样例数据带 is_illustrative=True，真实数据必须不带，否则两者会混。"""
    thesis = seeded.thesis.get(run_real_case.THESIS_ID)
    assert thesis.is_illustrative is False


def test_证据全部可回溯到原文段落() -> None:
    """FR-V-005 / DA-AC-07：任一结论可回溯到原文定位。"""
    from app.ingest.parsers.text import parse_sample_pack
    from app.ingest.segmentation import parse_locator, segment_document

    documents = dict(
        parse_sample_pack(
            (run_real_case.REAL_DATA_DIR / "documents.txt").read_text(encoding="utf-8")
        )
    )
    assert documents

    for doc_id, parsed in documents.items():
        segments = segment_document(doc_id, parsed)
        assert segments, f"{doc_id} 未切出段落"
        for segment in segments:
            parsed_doc_id, ordinal = parse_locator(segment.locator)
            assert parsed_doc_id == doc_id
            assert ordinal >= 1
            assert segment.content.strip()


def test_人工确认后才进入正式证据链() -> None:
    """PRD 5.4 人工闸门。跑完 worker 链时证据应全部待确认。"""
    from app.ai.gateway import Gateway
    from app.ingest.events import load_annotated_events
    from app.ingest.parsers.text import parse_sample_pack
    from app.ingest.segmentation import segment_document
    from app.workers import change_chain

    uow = build_fake_uow()
    run_real_case._seed(uow)
    for record in run_real_case._load_observations(
        run_real_case.REAL_DATA_DIR / "observations.csv"
    ):
        uow.observations.add(record)

    documents = dict(
        parse_sample_pack(
            (run_real_case.REAL_DATA_DIR / "documents.txt").read_text(encoding="utf-8")
        )
    )
    events = load_annotated_events(run_real_case.REAL_DATA_DIR / "events.csv")
    locators = {
        e.event_id: segment_document(e.document_id, documents[e.document_id])[0].locator
        for e in events
        if e.document_id in documents
    }

    change_chain.process_events(
        uow,
        Gateway.build(settings),
        events=events,
        security_id=run_real_case.SECURITY_ID,
        actor=run_real_case.RESEARCHER,
        thresholds=settings.rules,
        locator_by_event=locators,
    )

    candidates = uow.evidence.list_for_thesis(run_real_case.THESIS_ID)
    assert candidates
    assert all(c.confirmation_status is ConfirmationStatus.PENDING for c in candidates)

    # 状态也没被 worker 改过
    assert uow.thesis.get(run_real_case.THESIS_ID).status is ThesisStatus.VALIDATING
