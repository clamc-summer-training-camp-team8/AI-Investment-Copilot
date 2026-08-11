from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.ai.backend_adapter import (
    analyze_backend_event,
    build_runtime,
    draft_backend_document,
    to_agent_event,
)
from app.ai.gateway import Gateway
from app.ai.integration import to_backend_envelope
from app.core.config import Settings


def _runtime():
    return build_runtime(Gateway.build(Settings(_env_file=None, llm_provider="mock")))


def test_adapter_maps_integrated_event_and_hypotheses_to_runtime() -> None:
    execution = analyze_backend_event(
        _runtime(),
        event={
            "event_id": "EV-001",
            "document_id": "DOC-001",
            "summary": "公司收入增长。",
            "evidence_locator": "DOC-001#paragraph-1",
            "disclosure_time": "2026-08-10T09:00:00+08:00",
            "event_type": "业绩",
        },
        hypotheses=[
            {"thesis_id": "THS-001", "hypothesis_id": "H-001", "statement": "收入增长"}
        ],
        security_id="000538.SZ",
    )

    assert execution.task == "event_impact"
    assert execution.status == "needs_human_review"
    envelope = to_backend_envelope(execution)
    assert envelope["envelope_version"] == "ai-runtime-envelope-v1"
    assert envelope["candidate_result"]["event_id"] == "EV-001"


def test_adapter_accepts_integrated_dataclass_like_objects() -> None:
    event = SimpleNamespace(
        event_id="EV-002",
        document_id="DOC-002",
        summary="订单持续提升。",
        evidence_locator="DOC-002#paragraph-2",
        disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        event_type="订单",
        occurred_on=None,
    )

    normalized = to_agent_event(event, security_id="000538.SZ")

    assert normalized.event_id == "EV-002"
    assert normalized.security_id == "000538.SZ"
    assert normalized.disclosure_time.tzinfo is not None


def test_adapter_maps_document_segments_for_thesis_draft() -> None:
    execution = draft_backend_document(
        _runtime(),
        security_id="000538.SZ",
        view="订单增长",
        document_id="DOC-003",
        segments=[
            SimpleNamespace(
                document_id="DOC-003",
                locator="DOC-003#paragraph-1",
                content="订单增长，收入提升。",
            )
        ],
        published_at="2026-08-01T00:00:00+00:00",
    )

    assert execution.task == "thesis_draft"
    assert execution.status == "completed"
    assert execution.result.outcome.usable
    assert execution.retrieval_versions == ("keyword-v1",)


def test_adapter_rejects_event_without_locator() -> None:
    with pytest.raises(ValueError, match="evidence_locator"):
        to_agent_event(
            {"event_id": "EV-004", "document_id": "DOC-004", "summary": "公告"},
            security_id="000538.SZ",
        )
