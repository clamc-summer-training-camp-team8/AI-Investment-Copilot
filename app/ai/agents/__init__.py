"""投研 Agent 能力模块的稳定导出入口。"""

from app.ai.agents.evidence import EvidenceAgent
from app.ai.agents.logic_change import InvestmentLogicChangeAgent
from app.ai.agents.metric_explain import MetricExplainAgent
from app.ai.agents.review import ReviewAgent
from app.ai.agents.thesis_draft import ThesisDraftAgent
from app.ai.agents.types import (
    AgentEvent,
    AgentImpact,
    AgentRunResult,
    CandidateHypothesis,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
    MetricExplainRunResult,
    ReviewDraftRunResult,
    ThesisDraftRunResult,
)

__all__ = [
    "AgentEvent",
    "AgentImpact",
    "AgentRunResult",
    "CandidateHypothesis",
    "EvidenceAgent",
    "EvidenceConsistency",
    "EvidenceGrade",
    "EvidenceValidation",
    "InvestmentLogicChangeAgent",
    "MetricExplainAgent",
    "MetricExplainRunResult",
    "ReviewAgent",
    "ReviewDraftRunResult",
    "ThesisDraftAgent",
    "ThesisDraftRunResult",
]
