"""投研 Agent 能力模块的稳定导出入口。"""

from app.ai.agents.evidence import EvidenceAgent
from app.ai.agents.logic_change import InvestmentLogicChangeAgent
from app.ai.agents.metric_explain import MetricExplainAgent
from app.ai.agents.review import ReviewAgent
from app.ai.agents.thesis_draft import ThesisDraftAgent
from app.ai.agents.types import (
    AgentEventInput,
    AgentImpact,
    AgentRunResult,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
    HypothesisInput,
    MetricExplainRunResult,
    MetricRuleInput,
    ReviewDraftRunResult,
    ThesisDraftRunResult,
)

__all__ = [
    "AgentEventInput",
    "AgentImpact",
    "AgentRunResult",
    "EvidenceAgent",
    "EvidenceConsistency",
    "EvidenceGrade",
    "EvidenceValidation",
    "HypothesisInput",
    "InvestmentLogicChangeAgent",
    "MetricExplainAgent",
    "MetricExplainRunResult",
    "MetricRuleInput",
    "ReviewAgent",
    "ReviewDraftRunResult",
    "ThesisDraftAgent",
    "ThesisDraftRunResult",
]
