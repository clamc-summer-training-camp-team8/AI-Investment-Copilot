"""兼容导出入口。

新代码优先从 ``app.ai.agents`` 或具体能力模块导入。保留本模块是为了避免拆分目录时
破坏后端和已有测试使用的 ``from app.ai.agent import ...``。
"""

from app.ai.agents import (
    AgentEvent,
    AgentImpact,
    AgentRunResult,
    CandidateHypothesis,
    EvidenceAgent,
    EvidenceConsistency,
    EvidenceGrade,
    EvidenceValidation,
    InvestmentLogicChangeAgent,
    MetricExplainAgent,
    MetricExplainRunResult,
    ReviewAgent,
    ReviewDraftRunResult,
    ThesisDraftAgent,
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
