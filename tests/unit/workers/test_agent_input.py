from __future__ import annotations

from datetime import datetime

import pytest

from app.core.domain import DocumentSegmentRecord
from app.ingest.events import ExtractedEvent
from app.workers.agent_input import (
    EventEvidenceUnavailable,
    build_event_agent_inputs,
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
