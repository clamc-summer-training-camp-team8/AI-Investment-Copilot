from datetime import date, datetime
from decimal import Decimal

from app.api.feed_presenter import aggregate_feed_items, apply_daily_logic_digests
from app.core.domain import LogicChangeDigestRecord
from app.schemas.thesis import EvidenceFeedItemOut


def _item(
    *,
    evidence_id: str,
    document_id: str,
    hypothesis_id: str,
    hypothesis_statement: str,
    direction: str,
) -> EvidenceFeedItemOut:
    return EvidenceFeedItemOut(
        evidence_id=evidence_id,
        relation_id=f"REL-{evidence_id}",
        security_id="002594",
        security_name="比亚迪",
        thesis_id="THS-BYD-001",
        thesis_title="比亚迪主投资逻辑",
        thesis_core_view="销量增长与垂直一体化支撑盈利",
        source_document_id=document_id,
        hypothesis_id=hypothesis_id,
        hypothesis_statement=hypothesis_statement,
        source_document_title=f"资料 {evidence_id}",
        fact_excerpt=f"{evidence_id} 的事实摘录",
        disclosed_at=datetime(2026, 8, 31, 9, 0),
        ingested_at=datetime(2026, 8, 31, 10, 0),
        source_url="https://example.com/source",
        direction=direction,
        strength="高",
        ai_confidence=Decimal("0.8"),
        confirmation_status="待确认",
        priority="high",
        can_manage=True,
        validation_items=[],
    )


def test_当天按公司主投资逻辑聚合并保留假设影响路径() -> None:
    cards = aggregate_feed_items(
        [
            _item(
                evidence_id="EVD-001",
                document_id="DOC-MIXED",
                hypothesis_id="HYP-MARGIN",
                hypothesis_statement="规模效应与垂直一体化维持毛利率",
                direction="支持",
            ),
            _item(
                evidence_id="EVD-002",
                document_id="DOC-MIXED",
                hypothesis_id="HYP-MARGIN",
                hypothesis_statement="规模效应与垂直一体化维持毛利率",
                direction="冲突",
            ),
            _item(
                evidence_id="EVD-003",
                document_id="DOC-SUPPORT",
                hypothesis_id="HYP-SALES",
                hypothesis_statement="销量与出口结构改善支撑收入增长",
                direction="支持",
            ),
            _item(
                evidence_id="EVD-003",
                document_id="DOC-SUPPORT",
                hypothesis_id="HYP-EXPORT",
                hypothesis_statement="海外扩张改善收入结构与规模效应",
                direction="支持",
            ),
            _item(
                evidence_id="EVD-005",
                document_id="DOC-CONFLICT",
                hypothesis_id="HYP-PRICE",
                hypothesis_statement="价格竞争不会持续侵蚀盈利能力",
                direction="冲突",
            ),
        ],
        daily=True,
    )

    assert len(cards) == 1
    card = cards[0]
    assert card.theme_direction == "mixed"
    assert card.source_document_count == 3
    assert card.affected_hypothesis_count == 4
    assert card.support_evidence_count == 3
    assert card.conflict_evidence_count == 2
    assert "主投资逻辑出现分歧" in (card.aggregation_summary or "")
    assert [
        (impact.hypothesis_id, impact.direction, impact.has_conflicting_evidence)
        for impact in card.theme_impacts
    ] == [
        ("HYP-MARGIN", "中性", True),
        ("HYP-SALES", "支持", False),
        ("HYP-EXPORT", "支持", False),
        ("HYP-PRICE", "冲突", False),
    ]


def test_当天卡片优先显示已持久化的_llm_归并摘要() -> None:
    card = aggregate_feed_items(
        [
            _item(
                evidence_id="EVD-001",
                document_id="DOC-1",
                hypothesis_id="HYP-MARGIN",
                hypothesis_statement="规模效应维持毛利率",
                direction="冲突",
            )
        ],
        daily=True,
    )[0]
    digest = LogicChangeDigestRecord(
        digest_id="LCD-1",
        security_id="002594",
        thesis_id="THS-BYD-001",
        business_date=date(2026, 8, 31),
        overall_direction="混合",
        summary="订单与出口改善仍在，但价格压力需要与毛利率数据一并复核。",
        hypothesis_impacts=[
            {
                "hypothesis_id": "HYP-MARGIN",
                "direction": "分歧",
                "rationale": "支持与冲突证据并存。",
                "evidence_ids": ["EVD-001"],
            }
        ],
    )

    updated = apply_daily_logic_digests([card], {("002594", "THS-BYD-001"): digest})[0]

    assert updated.aggregation_summary == digest.summary
    assert updated.theme_direction == "mixed"
    assert updated.theme_impacts[0].direction == "中性"
    assert updated.theme_impacts[0].has_conflicting_evidence is True
