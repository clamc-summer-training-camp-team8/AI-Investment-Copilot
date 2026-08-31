"""投资逻辑草稿的假设集合质量检查能力。"""

from __future__ import annotations

from typing import Any

from app.ai.contracts.validator import ValidationOutcome
from app.ai.gateway import Gateway


class HypothesisQualityAgent:
    """让模型逐条检查假设维度、重复和交叉，不读取期间证据。"""

    def __init__(self, *, gateway: Gateway) -> None:
        self.gateway = gateway

    def inspect(
        self,
        *,
        security_id: str,
        thesis_id: str,
        title: str,
        core_view: str,
        hypotheses: list[dict[str, Any]],
    ) -> ValidationOutcome:
        return self.gateway.hypothesis_quality(
            security_id=security_id,
            thesis_id=thesis_id,
            title=title,
            core_view=core_view,
            hypotheses=hypotheses,
        )
