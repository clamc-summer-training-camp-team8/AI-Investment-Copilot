from __future__ import annotations

import json
from datetime import UTC, datetime

from app.ai.agent import (
    AgentEventInput,
    HypothesisInput,
    InvestmentLogicChangeAgent,
    ThesisDraftAgent,
)
from app.ai.gateway import Gateway
from app.ai.integration import to_backend_envelope
from app.ai.providers.mock import MockProvider
from app.ai.retrieval import KeywordRetriever
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings


def test_backend_envelope_is_json_serializable_and_versioned() -> None:
    retriever = KeywordRetriever()
    gateway = Gateway.build(Settings(_env_file=None, llm_provider="mock"))
    runtime = InvestmentResearchAgent(
        thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=retriever),
        logic_change=InvestmentLogicChangeAgent(gateway=gateway, retriever=retriever),
    )
    execution = runtime.analyze_event(
        AgentEventInput(
            event_id="event-001",
            document_id="doc-001",
            security_id="000538.SZ",
            evidence_locator="doc-001#paragraph-1",
            fact="收入增长",
            disclosure_time=datetime(2026, 8, 10, tzinfo=UTC),
            event_type="其他",
        ),
        HypothesisInput("THESIS-001", "H1", "收入增长"),
    )

    envelope = to_backend_envelope(execution)

    json.dumps(envelope, ensure_ascii=False)
    assert envelope["envelope_version"] == "ai-runtime-envelope-v1"
    assert envelope["status"] == "needs_human_review"
    assert envelope["versions"]["schema_name"] == "event_impact"
    assert envelope["versions"]["schema_id"].endswith("event_impact.schema.json")
    assert not envelope["retryable"]


def test_provider_or_schema_failure_is_degraded_and_retryable() -> None:
    settings = Settings(_env_file=None, llm_provider="mock")
    gateway = Gateway(settings=settings, provider=MockProvider(settings, event_payload={}))
    retriever = KeywordRetriever()
    runtime = InvestmentResearchAgent(
        thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=retriever),
        logic_change=InvestmentLogicChangeAgent(gateway=gateway, retriever=retriever),
    )
    execution = runtime.analyze_event(
        AgentEventInput(
            event_id="event-001",
            document_id="doc-001",
            security_id="000538.SZ",
            evidence_locator="doc-001#paragraph-1",
            fact="收入增长",
            disclosure_time=datetime(2026, 8, 10, tzinfo=UTC),
            event_type="其他",
        ),
        HypothesisInput("THESIS-001", "H1", "收入增长"),
    )

    envelope = to_backend_envelope(execution)

    assert execution.status == "degraded"
    assert execution.degraded_reason == "provider_or_schema_failure"
    assert envelope["retryable"]
    assert envelope["errors"]
