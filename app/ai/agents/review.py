"""阶段复盘草稿能力。"""

from __future__ import annotations

from datetime import date

from app.ai.agents.types import ReviewDraftRunResult
from app.ai.gateway import Gateway


class ReviewAgent:
    """从已有记录生成复盘草稿；不引入事实、不改变正式状态。"""

    def __init__(self, *, gateway: Gateway) -> None:
        self.gateway = gateway

    def generate(
        self,
        *,
        security_id: str,
        thesis_id: str,
        period_start: date,
        period_end: date,
        records: list[dict[str, object]],
    ) -> ReviewDraftRunResult:
        if period_end < period_start:
            raise ValueError("复盘结束日期不能早于开始日期")
        outcome = self.gateway.review_draft(
            security_id=security_id,
            thesis_id=thesis_id,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            records=records,
        )
        return ReviewDraftRunResult(security_id, thesis_id, outcome)
