"""投资逻辑变化 Agent 的最小编排器。

Agent 只编排检索和 AI 候选分析，不写数据库、不发布 Thesis、不改变正式状态。
后端可以把 `AgentRunResult.impacts` 转换为候选 Evidence 和 StatusSuggestion。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import date, datetime

from app.ai.gateway import Gateway
from app.ai.retrieval import (
    RetrievedChunk,
    RetrievalDocument,
    RetrievalQuery,
    RetrievalResult,
    Retriever,
)
from app.ai.contracts.validator import ValidationOutcome


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    document_id: str
    security_id: str
    segment_locator: str
    segment_text: str
    disclosure_time: datetime
    event_type: str = "其他"
    occurred_on: date | None = None


@dataclass(frozen=True)
class CandidateHypothesis:
    thesis_id: str
    hypothesis_id: str
    statement: str


@dataclass(frozen=True)
class AgentImpact:
    candidate: CandidateHypothesis
    retrieval: RetrievalResult
    outcome: ValidationOutcome


@dataclass(frozen=True)
class AgentRunResult:
    event_id: str
    impacts: list[AgentImpact]


@dataclass(frozen=True)
class ThesisDraftRunResult:
    security_id: str
    retrieval: RetrievalResult
    outcome: ValidationOutcome


class ThesisDraftAgent:
    """用观点和/或资料编排初始 Thesis 草稿；不写库、不发布正式 Thesis。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

    def generate(
        self,
        *,
        security_id: str,
        view: str = "",
        source_document_id: str | None = None,
        source_segments: list[RetrievalDocument] | None = None,
        as_of: datetime | None = None,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 8,
    ) -> ThesisDraftRunResult:
        """先检索资料，再把带 locator 的片段传给 Gateway。"""
        if source_segments:
            self.retriever.add(source_segments)
        query_text = view or " ".join(
            document.content for document in (source_segments or [])
        )
        retrieval = self.retriever.search(
            RetrievalQuery(
                text=query_text,
                security_id=security_id,
                as_of=as_of,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
        )
        segments = [(item.locator, item.content) for item in retrieval.items]
        if not segments and source_segments:
            segments = [(item.locator, item.content) for item in source_segments[:top_k]]
        outcome = self.gateway.thesis_draft(
            security_id=security_id,
            view=view,
            segments=segments,
            source_document_id=source_document_id,
        )
        return ThesisDraftRunResult(
            security_id=security_id,
            retrieval=retrieval,
            outcome=outcome,
        )

@dataclass(frozen=True)
class EvidenceValidation:
    valid: bool
    cited_locators: tuple[str, ...]
    missing_locators: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    requires_human_review: bool


@dataclass(frozen=True)
class EvidenceGrade:
    score: float
    passed: bool
    cited_count: int
    valid_cited_count: int
    source_count: int
    stale_count: int
    missing: tuple[str, ...]

@dataclass(frozen=True)
class EvidenceConsistency:
    entity_matched: bool
    fact_supported: bool
    conflicting: bool
    reasons: tuple[str, ...]

class EvidenceAgent:
    """只校验证据边界，不写数据库，也不替换模型结论。"""

    @staticmethod
    def validate_impact(impact: AgentImpact) -> EvidenceValidation:
        payload = impact.outcome.payload
        allowed = {item.locator for item in impact.retrieval.items}
        event = payload.get("event")
        primary_locator = None
        if isinstance(event, dict) and event.get("evidence_locator"):
            primary_locator = str(event["evidence_locator"])
            allowed.add(primary_locator)
        citations = payload.get("citations")
        cited: list[str] = [primary_locator] if primary_locator else []
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict) and citation.get("locator"):
                    cited.append(str(citation["locator"]))
                elif isinstance(citation, str):
                    cited.append(citation)
        missing = sorted(set(cited) - allowed)
        unsupported = payload.get("unsupported_claims")
        unsupported_claims = tuple(str(item) for item in unsupported) if isinstance(unsupported, list) else ()
        valid = bool(cited) and not missing and not unsupported_claims
        signal = payload.get("signal")
        model_requires_review = not isinstance(signal, dict) or bool(
            signal.get("requires_human_review", True)
        )
        return EvidenceValidation(
            valid=valid,
            cited_locators=tuple(dict.fromkeys(cited)),
            missing_locators=tuple(missing),
            unsupported_claims=unsupported_claims,
            requires_human_review=(
                model_requires_review or not valid or impact.outcome.ai_status.value != "候选"
            ),
        )

    @staticmethod
    def check_consistency(impact: AgentImpact) -> EvidenceConsistency:
        payload = impact.outcome.payload
        reasons: list[str] = []
        security_id = str(payload.get("security_id") or "")
        entity_matched = bool(security_id) and any(
            chunk.security_id == security_id for chunk in impact.retrieval.items
        )
        if not entity_matched:
            reasons.append("entity_mismatch")
        event = payload.get("event")
        fact = str(event.get("fact") or "") if isinstance(event, dict) else ""
        cited = {item.locator for item in impact.retrieval.items}
        cited_text = " ".join(item.content for item in impact.retrieval.items if item.locator in cited)
        fact_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", fact))
        context_tokens = set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", cited_text))
        fact_supported = not fact or len(fact_tokens & context_tokens) >= 2
        if not fact_supported:
            reasons.append("fact_not_supported")
        positive = any(cue in cited_text or cue in fact for cue in ("增长", "提升", "改善", "增加"))
        negative = any(cue in cited_text or cue in fact for cue in ("下降", "压力", "风险", "减少"))
        conflicting = positive and negative
        if conflicting:
            reasons.append("conflicting_evidence")
        return EvidenceConsistency(entity_matched, fact_supported, conflicting, tuple(reasons))
    @staticmethod
    def grade_impact(impact: AgentImpact, *, max_age_days: int = 180) -> EvidenceGrade:
        """为候选影响结果计算可解释的证据完整性分数。"""
        validation = EvidenceAgent.validate_impact(impact)
        cited = set(validation.cited_locators)
        valid_cited = cited - set(validation.missing_locators)
        sources = {item.source for item in impact.retrieval.items if item.locator in valid_cited}
        disclosure_time = None
        event = impact.outcome.payload.get("event")
        if isinstance(event, dict) and event.get("disclosure_time"):
            try:
                disclosure_time = datetime.fromisoformat(str(event["disclosure_time"]))
            except ValueError:
                pass
        stale_count = 0
        if disclosure_time is not None:
            for item in impact.retrieval.items:
                if item.locator in valid_cited and (disclosure_time - item.published_at).days > max_age_days:
                    stale_count += 1
        missing = list(validation.missing_locators)
        if not validation.cited_locators:
            missing.append("citations")
        if validation.unsupported_claims:
            missing.append("unsupported_claims")
        citation_score = min(len(valid_cited) / 2, 1.0)
        source_score = min(len(sources) / 2, 1.0)
        freshness_score = 0.0 if stale_count else 1.0
        score = round(0.6 * citation_score + 0.2 * source_score + 0.2 * freshness_score, 3)
        return EvidenceGrade(score=score, passed=not missing and score >= 0.6, cited_count=len(cited), valid_cited_count=len(valid_cited), source_count=len(sources), stale_count=stale_count, missing=tuple(sorted(set(missing))))

    @staticmethod
    def validate_run(result: AgentRunResult) -> list[EvidenceValidation]:
        return [EvidenceAgent.validate_impact(impact) for impact in result.impacts]

class InvestmentLogicChangeAgent:
    """把新事件编排为一组面向具体假设的候选影响结果。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

    @staticmethod
    def _context(candidate: CandidateHypothesis, chunks: list[RetrievedChunk]) -> str:
        lines = [f"目标假设：{candidate.statement}"]
        lines.extend(f"{chunk.locator}: {chunk.content}" for chunk in chunks)
        return "\n".join(lines)

    def analyze(
        self,
        event: AgentEvent,
        candidates: list[CandidateHypothesis],
        *,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 3,
    ) -> AgentRunResult:
        impacts: list[AgentImpact] = []
        for candidate in candidates:
            retrieval = self.retriever.search(
                RetrievalQuery(
                    text=f"{event.segment_text} {candidate.statement}",
                    security_id=event.security_id,
                    as_of=event.disclosure_time,
                    allowed_visibility=allowed_visibility,
                    top_k=top_k,
                )
            )
            outcome = self.gateway.event_impact(
                document_id=event.document_id,
                security_id=event.security_id,
                segment_locator=event.segment_locator,
                segment_text=event.segment_text,
                disclosure_time=event.disclosure_time.isoformat(),
                thesis_id=candidate.thesis_id,
                hypothesis_id=candidate.hypothesis_id,
                event_type=event.event_type,
                occurred_on=event.occurred_on.isoformat() if event.occurred_on else None,
                context=self._context(candidate, retrieval.items),
            )
            impacts.append(AgentImpact(candidate, retrieval, outcome))
        return AgentRunResult(event_id=event.event_id, impacts=impacts)


@dataclass(frozen=True)
class MetricExplainRunResult:
    security_id: str
    hypothesis_id: str
    outcome: ValidationOutcome


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


@dataclass(frozen=True)
class ReviewDraftRunResult:
    security_id: str
    thesis_id: str
    outcome: ValidationOutcome


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