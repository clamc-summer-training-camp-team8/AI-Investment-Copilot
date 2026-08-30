from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.domain import LogicTopicRecord, LogicTopicRelationRecord
from app.ranking.builder import PriorInput, build_snapshot
from app.ranking.features import PriorFeatures, topic_prior
from app.services.topic_retrieval import ranked_topic_context
from tests.fakes import build_fake_uow


def test_topic_prior_rewards_quality_and_penalizes_unresolved_conflict() -> None:
    strong = PriorFeatures(
        business_materiality=0.9,
        evidence_strength=0.8,
        persistence=0.8,
        verifiability=0.9,
        company_specificity=0.9,
        causal_strength=0.8,
        recency=0.8,
        conflict_attention=0.8,
        unresolved_conflict_severity=0.1,
    )
    conflicted = PriorFeatures(
        **{
            **strong.as_dict(),
            "unresolved_conflict_severity": 0.9,
        }
    )
    assert topic_prior(strong) > topic_prior(conflicted)
    assert round(topic_prior(strong) - topic_prior(conflicted), 2) == 0.16


def test_topic_prior_applies_primary_gate_penalty() -> None:
    eligible = PriorFeatures(business_materiality=0.9, verifiability=0.8)
    ineligible = PriorFeatures(business_materiality=0.9, verifiability=0.8, low_value_penalty=1.0)
    assert round(topic_prior(eligible) - topic_prior(ineligible), 2) == 0.25


def test_primary_eligible_topic_ranks_before_higher_scored_narrow_topic() -> None:
    uow = build_fake_uow()
    snapshot = build_snapshot(
        uow,
        security_id="00175",
        direction="观察",
        horizon="12M",
        as_of=datetime(2026, 8, 24, tzinfo=UTC),
        ranker_version="logic-topic-prior-v1",
        feature_version="logic-topic-features-v1",
        inputs=[
            PriorInput(
                object_type="logic_topic",
                object_id="NARROW",
                features=PriorFeatures(business_materiality=1.0),
                reason_codes=("PRIMARY_TOPIC_GATE_FAILED",),
            ),
            PriorInput(
                object_type="logic_topic",
                object_id="ELIGIBLE",
                features=PriorFeatures(business_materiality=0.6),
                reason_codes=("PRIMARY_TOPIC_ELIGIBLE",),
            ),
        ],
    )
    ranked = uow.ranking.ranked_items(snapshot.snapshot_id, object_type="logic_topic", limit=2)
    assert [row.object_id for row in ranked] == ["ELIGIBLE", "NARROW"]


def test_ranked_topic_context_returns_primary_and_relations() -> None:
    uow = build_fake_uow()
    as_of = datetime(2026, 8, 24, tzinfo=UTC)
    topic = LogicTopicRecord(
        topic_id="TOPIC-1",
        security_id="00175",
        name="产品结构升级",
        normalized_statement="高端车型占比提升推动盈利改善",
        direction="看多",
        horizon="12M",
        source_thesis_ids=["THESIS-1"],
    )
    uow.ranking.upsert_topics([topic])
    uow.ranking.upsert_topic_relations(
        [
            LogicTopicRelationRecord(
                relation_id="LTR-1",
                topic_id=topic.topic_id,
                object_type="evidence",
                object_id="EVD-1",
                relation="支持",
                confidence=Decimal("0.9"),
                source="deterministic_v1",
                citation_locators=["DOC-1#paragraph-1"],
            )
        ]
    )
    snapshot = build_snapshot(
        uow,
        security_id="00175",
        direction="看多",
        horizon="12M",
        as_of=as_of,
        ranker_version="logic-topic-prior-v1",
        feature_version="logic-topic-features-v1",
        inputs=[
            PriorInput(
                object_type="logic_topic",
                object_id=topic.topic_id,
                features=PriorFeatures(business_materiality=0.9),
            )
        ],
    )
    snapshot_id, rows = ranked_topic_context(
        uow, security_id="00175", direction="看多", horizon="12M", as_of=as_of, limit=3
    )
    assert snapshot_id == snapshot.snapshot_id
    assert rows[0]["topic_id"] == "TOPIC-1"
    assert rows[0]["relations"]["evidence"][0]["object_id"] == "EVD-1"
    assert rows[0]["primary_eligible"] is False
