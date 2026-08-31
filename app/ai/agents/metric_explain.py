"""确定性指标计算结果的解释能力。"""

from __future__ import annotations

from app.ai.agents.types import MetricExplainRunResult
from app.ai.gateway import Gateway


class MetricExplainAgent:
    """只解释 app.calc 输出，不让模型承担关键数值计算。"""

    def __init__(self, *, gateway: Gateway) -> None:
        self.gateway = gateway

    def explain(
        self,
        *,
        security_id: str,
        hypothesis_id: str,
        hypothesis: str,
        calc_result: dict[str, object],
    ) -> MetricExplainRunResult:
        outcome = self.gateway.metric_explain(
            security_id=security_id,
            hypothesis_id=hypothesis_id,
            hypothesis=hypothesis,
            calc_result=calc_result,
        )
        return MetricExplainRunResult(security_id, hypothesis_id, outcome)
