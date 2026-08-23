from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.ai.retrieval import KeywordRetriever, RetrievalQuery
from app.core.domain import AssetSearchHitRecord, DocumentSegmentRecord
from app.ingest.events import ExtractedEvent
from app.workers.agent_input import (
    EventEvidenceUnavailable,
    build_event_agent_inputs,
    build_historical_rag_context,
    index_current_event_segments,
)


def _event() -> ExtractedEvent:
    return ExtractedEvent(
        event_id="EV-CAPACITY-1",
        document_id="DOC-CAPACITY-1",
        security_id="SEC-1",
        event_type="经营指标",
        summary="产能利用率下降",
        disclosure_time=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        fingerprint="fp-capacity-1",
        evidence_locator="DOC-CAPACITY-1#paragraph-7",
    )


def test_event_fact_and_evidence_segment_are_kept_separate() -> None:
    segment = DocumentSegmentRecord(
        document_id="DOC-CAPACITY-1",
        locator="DOC-CAPACITY-1#paragraph-7",
        ordinal=7,
        content="公司第二季度产能利用率为72%，较上一季度下降6个百分点。",
    )

    inputs = build_event_agent_inputs(
        event=_event(),
        security_id="SEC-1",
        segments_by_locator=index_current_event_segments([segment]),
        visibility_label="公开",
        source="第二季度经营公告",
    )

    assert inputs.event.fact == "产能利用率下降"
    assert inputs.current_event_evidence.content == segment.content
    assert inputs.current_event_evidence.content != inputs.event.fact
    assert inputs.current_event_evidence.locator == inputs.event.evidence_locator
    assert inputs.current_event_evidence.document_id == inputs.event.document_id


def test_missing_event_segment_never_falls_back_to_event_summary() -> None:
    with pytest.raises(EventEvidenceUnavailable, match="无法回查原文"):
        build_event_agent_inputs(
            event=_event(),
            security_id="SEC-1",
            segments_by_locator={},
            visibility_label="公开",
            source="第二季度经营公告",
        )


def test_historical_rag_metadata_is_preserved_without_locator_inference() -> None:
    published_at = datetime.fromisoformat("2026-08-01T09:00:00+08:00")
    hit = AssetSearchHitRecord(
        document_id="DOC-HISTORY-001",
        locator="opaque-locator-7",
        content="公司第一季度产能利用率为78%。",
        visibility_label="team-a",
        rank=0.87,
        published_at=published_at,
        source="2026年第一季度经营报告",
        retrieval_mode="hybrid",
    )

    context = build_historical_rag_context(security_id="SEC-1", hits=[hit])

    assert len(context) == 1
    document = context[0]
    assert document.document_id == "DOC-HISTORY-001"
    assert document.locator == "opaque-locator-7"
    assert document.content == hit.content
    assert document.published_at == published_at
    assert document.visibility_label == "team-a"
    assert document.source == "2026年第一季度经营报告"


def test_historical_rag_as_of_keeps_only_available_document_metadata() -> None:
    event_time = datetime.fromisoformat("2026-08-12T09:00:00+08:00")
    past_time = event_time - timedelta(days=1)
    future_time = event_time + timedelta(days=1)
    hits = [
        AssetSearchHitRecord(
            document_id="DOC-PAST",
            locator="LOC-PAST",
            content="产能利用率为78%",
            visibility_label="team-a",
            rank=0.9,
            published_at=past_time,
            source="历史经营报告",
        ),
        AssetSearchHitRecord(
            document_id="DOC-FUTURE",
            locator="LOC-FUTURE",
            content="产能利用率为82%",
            visibility_label="team-a",
            rank=0.95,
            published_at=future_time,
            source="未来经营报告",
        ),
    ]
    retriever = KeywordRetriever()
    retriever.add(build_historical_rag_context(security_id="SEC-1", hits=hits))

    result = retriever.search(
        RetrievalQuery(
            text="产能利用率",
            security_id="SEC-1",
            as_of=event_time,
            allowed_visibility=frozenset({"team-a"}),
        )
    )

    assert [item.document_id for item in result.items] == ["DOC-PAST"]
    assert result.items[0].published_at == past_time
    assert result.items[0].source == "历史经营报告"
    assert result.items[0].visibility_label == "team-a"
