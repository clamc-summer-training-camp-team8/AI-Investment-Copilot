from __future__ import annotations

from datetime import date

from app.ai.agent import InvestmentLogicChangeAgent, ThesisDraftAgent
from app.ai.gateway import Gateway
from app.ai.retrieval import KeywordRetriever
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings


def _runtime() -> InvestmentResearchAgent:
    retriever = KeywordRetriever()
    gateway = Gateway.build(Settings(_env_file=None, llm_provider="mock"))
    return InvestmentResearchAgent(
        thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=retriever),
        logic_change=InvestmentLogicChangeAgent(gateway=gateway, retriever=retriever),
    )


def test_metric_explain_only_consumes_deterministic_calc_result() -> None:
    execution = _runtime().explain_metric(
        security_id="000538.SZ",
        hypothesis_id="THESIS-001-H1",
        hypothesis="收入保持增长",
        calc_result={
            "verdict": "支持",
            "display_text": "收入同比为程序已计算结果，口径为季度累计。",
        },
    )

    assert execution.status == "completed"
    assert execution.schema_name == "metric_explain"
    assert execution.result.outcome.payload["calculation_source"] == "app.calc"
    assert execution.result.outcome.payload["summary"].startswith("收入同比")


def test_review_agent_summarizes_only_supplied_records_and_requires_review() -> None:
    execution = _runtime().draft_review(
        security_id="000538.SZ",
        thesis_id="THESIS-001",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 8, 10),
        records=[
            {
                "fact": "核心业务收入增长",
                "impact_direction": "支持",
                "locator": "doc-001#paragraph-1",
            },
            {
                "fact": "成本压力上升",
                "impact_direction": "冲突",
                "locator": "doc-002#paragraph-2",
            },
        ],
    )

    payload = execution.result.outcome.payload
    assert execution.status == "needs_human_review"
    assert payload["supporting_changes"] == ["核心业务收入增长"]
    assert payload["conflicting_changes"] == ["成本压力上升"]
    assert payload["citations"] == ["doc-001#paragraph-1", "doc-002#paragraph-2"]
    assert payload["requires_human_review"]
