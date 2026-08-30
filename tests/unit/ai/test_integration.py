from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.ai.agent import (
    AgentEventInput,
    AgentImpact,
    AgentRunResult,
    HypothesisInput,
    InvestmentLogicChangeAgent,
    ThesisDraftAgent,
)
from app.ai.contracts.validator import ValidationOutcome
from app.ai.gateway import Gateway
from app.ai.integration import (
    to_backend_analysis_result,
    to_backend_envelope,
    to_backend_impact_result,
)
from app.ai.providers.mock import MockProvider
from app.ai.retrieval import KeywordRetriever, RetrievalQuery, RetrievalResult, RetrievedChunk
from app.ai.runtime import InvestmentResearchAgent, RuntimeExecution
from app.core.config import Settings
from app.core.enums import AiStatus, ImpactDirection


def _impact(hypothesis_id: str, direction: ImpactDirection) -> AgentImpact:
    published_at = datetime(2026, 8, 10, tzinfo=UTC)
    locator = "doc-001#paragraph-1"
    return AgentImpact(
        candidate=HypothesisInput("THESIS-001", hypothesis_id, f"假设 {hypothesis_id}"),
        retrieval=RetrievalResult(
            query=RetrievalQuery(text="事件 假设", security_id="000538.SZ"),
            items=[
                RetrievedChunk(
                    document_id="doc-001",
                    security_id="000538.SZ",
                    locator=locator,
                    content="公司披露经营指标发生变化。",
                    published_at=published_at,
                    visibility_label="公开",
                    source="公司公告",
                    score=1.0,
                )
            ],
        ),
        outcome=ValidationOutcome(
            ai_status=AiStatus.CANDIDATE,
            payload={
                "event": {"evidence_locator": locator},
                "signal": {
                    "impact_direction": direction.value,
                    "strength": 0.7,
                    "confidence": 0.8,
                    "horizon": "中期",
                    "rationale": "经营指标变化影响原假设",
                    "transmission_path": "事件 → 指标变化 → 假设重估",
                    "requires_human_review": True,
                },
                "citations": [{"locator": locator}],
                "model_version": "model-v1",
                "prompt_version": "prompt-v1",
                "model_metadata": {"provider": "test"},
            },
        ),
    )


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
        (HypothesisInput("THESIS-001", "H1", "收入增长"),),
    )

    envelope = to_backend_envelope(execution)

    json.dumps(envelope, ensure_ascii=False)
    assert envelope["envelope_version"] == "ai-runtime-envelope-v1"
    assert envelope["status"] == "needs_human_review"
    assert envelope["versions"]["schema_name"] == "event_impact"
    assert envelope["versions"]["schema_id"].endswith("event_impact.schema.json")
    assert not envelope["retryable"]
    assert envelope["candidate_result"]["impacts"][0]["outcome"]["payload"]["signal"]


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
        (HypothesisInput("THESIS-001", "H1", "收入增长"),),
    )

    envelope = to_backend_envelope(execution)

    assert execution.status == "degraded"
    assert execution.degraded_reason == "provider_or_schema_failure"
    assert envelope["retryable"]
    assert envelope["errors"]


def test_single_impact_maps_to_stable_backend_result() -> None:
    result = to_backend_impact_result(_impact("H1", ImpactDirection.CONFLICT))

    assert result.thesis_id == "THESIS-001"
    assert result.hypothesis_id == "H1"
    assert result.impact_direction is ImpactDirection.CONFLICT
    assert result.strength_score == Decimal("0.7")
    assert result.confidence == Decimal("0.8")
    assert result.horizon == "中期"
    assert result.rationale == "经营指标变化影响原假设"
    assert result.transmission_path == "事件 → 指标变化 → 假设重估"
    assert result.citations == ("doc-001#paragraph-1",)
    assert result.ai_status is AiStatus.CANDIDATE
    assert result.validation_status == "valid"
    assert result.model_metadata == {"provider": "test"}


def test_multi_impact_mapping_keeps_identity_and_unrelated() -> None:
    impacts = [
        _impact("H1", ImpactDirection.CONFLICT),
        _impact("H2", ImpactDirection.CONFLICT),
        _impact("H3", ImpactDirection.IRRELEVANT),
    ]
    execution = RuntimeExecution(
        run_id="run-001",
        task="event_impact",
        result=AgentRunResult(event_id="event-001", impacts=impacts),
    )

    result = to_backend_analysis_result(execution)

    assert [item.hypothesis_id for item in result.impacts] == ["H1", "H2", "H3"]
    assert [item.impact_direction for item in result.impacts] == [
        ImpactDirection.CONFLICT,
        ImpactDirection.CONFLICT,
        ImpactDirection.IRRELEVANT,
    ]


def test_change_chain_does_not_read_agent_internal_payload() -> None:
    source = (
        Path(__file__).parents[3] / "app" / "workers" / "change_chain.py"
    ).read_text(encoding="utf-8")

    assert 'payload["signal"]' not in source
    assert ".outcome.payload" not in source
