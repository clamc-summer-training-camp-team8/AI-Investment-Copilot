from __future__ import annotations

from datetime import datetime, timezone

from app.ai.agents import AgentEvent, CandidateHypothesis
from app.ai.gateway import Gateway
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings


def _gateway() -> Gateway:
    return Gateway.build(Settings(_env_file=None, llm_provider="mock"))


def test_frontend_draft_route_gateway_contract_is_compatible() -> None:
    """覆盖 feat/react-frontend-mvp 的 create_draft 调用形状。"""
    outcome = _gateway().thesis_draft(
        security_id="000538.SZ",
        view="核心业务收入保持增长",
        segments=[],
        source_document_id=None,
    )

    assert outcome.usable
    assert {
        "security_id",
        "title",
        "core_view",
        "hypotheses",
        "model_version",
        "prompt_version",
    } <= outcome.payload.keys()
    assert 2 <= len(outcome.payload["hypotheses"]) <= 5


def test_frontend_change_worker_gateway_contract_is_compatible() -> None:
    """覆盖 feat/react-frontend-mvp 的 process_events 调用形状。"""
    outcome = _gateway().event_impact(
        document_id="DOC-001",
        security_id="000538.SZ",
        segment_locator="DOC-001#paragraph-1",
        segment_text="公司收入增长，订单持续提升。",
        disclosure_time="2026-08-10T09:00:00+08:00",
        thesis_id="THS-001",
        hypothesis_id="THS-001-H1",
        event_type="业绩",
        occurred_on="2026-08-10",
    )

    assert outcome.usable
    signal = outcome.payload["signal"]
    assert {
        "impact_direction",
        "strength",
        "confidence",
        "horizon",
        "requires_human_review",
    } <= signal.keys()
    assert outcome.payload["model_version"]
    assert outcome.payload["prompt_version"]


def test_runtime_build_exposes_typed_event_analysis() -> None:
    runtime = InvestmentResearchAgent.build(_gateway())

    execution = runtime.analyze_event(
        AgentEvent(
            event_id="EV-001",
            document_id="DOC-001",
            security_id="000538.SZ",
            segment_locator="DOC-001#paragraph-1",
            segment_text="公司收入增长。",
            disclosure_time=datetime(2026, 8, 10, tzinfo=timezone.utc),
        ),
        [CandidateHypothesis("THS-001", "THS-001-H1", "收入保持增长")],
    )

    assert execution.task == "event_impact"
    assert execution.status == "needs_human_review"
