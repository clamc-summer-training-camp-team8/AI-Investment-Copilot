from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class RankingJudgeUnavailable(RuntimeError):
    """The optional external ranking checker is disabled or unavailable."""


@dataclass(frozen=True)
class Judgement:
    object_id: str
    rank: int
    score: float
    confidence: float
    reason_codes: tuple[str, ...]
    citation_locators: tuple[str, ...]


class RankingJudge(Protocol):
    """高级检查模型的稳定端口；具体模型通过 Gateway 适配。"""

    def judge(self, candidates: list[dict[str, object]]) -> list[Judgement]: ...
