"""变化处理链（PRD 7.2）。

```
ingest.extract_events → ingest.dedupe
  → services.recall_candidates → ai.analyze_impact
  → calc（预期差 / 趋势 / 失效判定）
  → services.evidence.create_candidates → services.status.record_suggestion
```

**这条链止于候选证据与状态建议。** 不确认证据、不改状态。研究员在界面上确认后，
才由 `services.evidence.handle` 与 `services.status.apply_decision` 推进。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from hashlib import sha256

from app.ai.agents import AgentRunResult
from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.integration import to_backend_analysis_result
from app.ai.retrieval import KeywordRetriever, RetrievalDocument, RetrievalResult
from app.ai.runtime import InvestmentResearchAgent
from app.calc.rules import StatusSuggestion
from app.core.config import RuleThresholds, Settings
from app.core.domain import AssetSearchHitRecord
from app.core.enums import AiStatus, ConfirmationStatus, ImpactDirection
from app.ingest.events import ExtractedEvent, dedupe_events, to_strength_bucket
from app.services import assets as asset_service
from app.services import audit, thesis
from app.services import evidence as evidence_service
from app.services import relation as relation_service
from app.services import status as status_service
from app.services.graph_rag import (
    GraphRagCorpus,
    build_graph_rag_corpus,
    build_graph_retriever_from_corpus,
    graph_candidate_context,
)
from app.services.permission import Actor
from app.services.ports import (
    DocumentSegmentRecord,
    EvidenceRecord,
    HypothesisRecord,
    ThesisRecord,
    UnitOfWork,
)
from app.workers.agent_input import (
    EventAgentInputs,
    EventEvidenceUnavailable,
    build_event_agent_inputs,
    build_historical_rag_context,
    build_hypothesis_input,
    index_current_event_segments,
)


@dataclass(frozen=True)
class RecallTrace:
    rank: int
    thesis_id: str
    text_score: float
    graph_score: float
    fused_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "rank": self.rank,
            "thesis_id": self.thesis_id,
            "text_score": self.text_score,
            "graph_score": self.graph_score,
            "fused_score": self.fused_score,
        }


@dataclass
class ChangeResult:
    """一条资料的变化处理结果。"""

    document_id: str
    candidates: list[EvidenceRecord]
    suggestions: list[tuple[str, StatusSuggestion]]
    deferred: list[tuple[str, str]]
    matched_theses: list[str]
    retrieval_mode: str
    recall_traces: list[RecallTrace]
    graph_snapshot_id: str | None = None


def _pick_hypothesis(
    event: ExtractedEvent,
    hypotheses: list[object],
) -> str | None:
    """把事件落到具体假设上（FR-R-002）。

    优先用标注里已给的 hypothesis_id；没有时按关键词匹配假设陈述。匹配不到就
    返回 None——PRD 10.2 要求影响对象具体到核心假设，落不到假设的事件不该硬塞。
    """
    if event.hypothesis_id:
        return event.hypothesis_id

    best, best_score = None, 0
    for hypothesis in hypotheses:
        statement = str(getattr(hypothesis, "statement", ""))
        keyword_score = sum(
            1
            for token in (
                "订单",
                "收入",
                "毛利率",
                "装机",
                "需求",
                "政策",
                "产能",
                "价格",
                "成本",
                "现金流",
            )
            if token in statement and token in event.summary
        )
        # 兼容模型自由生成的可证伪表达：用中文双字组补充固定
        # 关键词，但仍要求存在语义交集，不把无关事件硬塞给某条假设。
        statement_terms = _bigrams(statement)
        event_terms = _bigrams(event.summary)
        overlap_score = min(len(statement_terms & event_terms), 10)
        score = keyword_score * 10 + overlap_score
        if score > best_score:
            best, best_score = str(getattr(hypothesis, "hypothesis_id", "")), score
    return best


def _bigrams(value: str) -> set[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    ignored = {"公司", "持续", "同比", "相关", "预期", "影响"}
    return {
        chunk[index : index + 2]
        for chunk in chunks
        for index in range(len(chunk) - 1)
        if chunk[index : index + 2] not in ignored
    }


def _overlap_score(query_terms: set[str], content: str) -> float:
    if not query_terms:
        return 0.0
    return len(query_terms & _bigrams(content)) / len(query_terms)


def _rank_candidates(
    recalled: list[tuple[ThesisRecord, list[HypothesisRecord]]],
    *,
    events: list[ExtractedEvent],
    graph_corpus: GraphRagCorpus | None,
    settings: Settings | None,
) -> tuple[list[tuple[ThesisRecord, list[HypothesisRecord]]], list[RecallTrace]]:
    if settings is None or not (settings.rag_graph_enabled or settings.rag_event_pilot_enabled):
        return recalled, [
            RecallTrace(index, record.thesis_id, 0.0, 0.0, 0.0)
            for index, (record, _) in enumerate(recalled, start=1)
        ]
    query_terms = set().union(*(_bigrams(event.summary) for event in events)) if events else set()
    graph_enabled = graph_corpus is not None
    text_weight = settings.rag_graph_text_weight if settings and graph_enabled else 1.0
    graph_weight = settings.rag_graph_relation_weight if settings and graph_enabled else 0.0
    total_weight = text_weight + graph_weight or 1.0
    scored: list[tuple[float, int, ThesisRecord, list[HypothesisRecord], float, float]] = []
    for original_rank, (record, hypotheses) in enumerate(recalled):
        text_context = " ".join(
            [record.title, record.core_view, *(hypothesis.statement for hypothesis in hypotheses)]
        )
        text_score = _overlap_score(query_terms, text_context)
        graph_score = (
            _overlap_score(query_terms, graph_candidate_context(graph_corpus, record.thesis_id))
            if graph_corpus
            else 0.0
        )
        fused = (text_weight * text_score + graph_weight * graph_score) / total_weight
        scored.append((fused, original_rank, record, hypotheses, text_score, graph_score))
    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked = [(record, hypotheses) for _, _, record, hypotheses, _, _ in scored]
    traces = [
        RecallTrace(
            rank=rank,
            thesis_id=record.thesis_id,
            text_score=round(text_score, 6),
            graph_score=round(graph_score, 6),
            fused_score=round(fused, 6),
        )
        for rank, (fused, _, record, _, text_score, graph_score) in enumerate(scored, start=1)
    ]
    return ranked, traces


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _rag_selected(event_id: str, sample_rate: float) -> bool:
    """Stable event-level sampling so retries never change the pilot cohort."""
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    bucket = int(sha256(event_id.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < sample_rate


def _retrieval_trace(result: RetrievalResult, *, locator: str) -> dict[str, object]:
    """冻结前端所需的检索依据；不复制正文，也不保存查询之外的图节点。"""

    selected = next((item for item in result.items if item.locator == locator), None)
    if selected is None and result.items:
        selected = result.items[0]
    if selected is None:
        return {
            "available": False,
            "retrieval_mode": "none",
            "retrieval_version": result.retrieval_version,
            "locator": locator,
            "final_score": 0.0,
            "score_components": {"text": 0.0, "graph": 0.0},
            "graph_paths": [],
            "graph_snapshot": None,
        }

    raw_components = selected.metadata.get("score_components")
    components = raw_components if isinstance(raw_components, dict) else {}
    raw_paths = selected.metadata.get("graph_paths")
    paths = raw_paths if isinstance(raw_paths, list) else []
    raw_snapshot = selected.metadata.get("graph_snapshot")
    snapshot = raw_snapshot if isinstance(raw_snapshot, dict) and raw_snapshot else None
    return {
        "available": True,
        "retrieval_mode": str(selected.metadata.get("retrieval_mode") or "text"),
        "retrieval_version": result.retrieval_version,
        "locator": selected.locator,
        "final_score": float(selected.score),
        "score_components": {
            "text": float(components.get("text", selected.score)),
            "graph": float(components.get("graph", 0.0)),
        },
        "graph_paths": [dict(path) for path in paths[:3] if isinstance(path, dict)],
        "graph_snapshot": dict(snapshot) if snapshot else None,
    }


def _rag_context(
    uow: UnitOfWork,
    *,
    event: ExtractedEvent,
    security_id: str,
    actor: Actor,
    settings: Settings | None,
) -> list[AssetSearchHitRecord]:
    if (
        settings is None
        or not settings.rag_event_pilot_enabled
        or not _rag_selected(event.event_id, settings.rag_event_pilot_sample_rate)
    ):
        return []
    hits = asset_service.hybrid_retrieve(
        uow,
        query=event.summary,
        actor=actor,
        settings=settings,
        security_ids=(security_id,),
        published_to=event.disclosure_time,
        limit=settings.rag_event_pilot_limit,
    )
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="RAG事件假设召回",
        object_type="event",
        object_id=event.event_id,
        detail={
            "embedding_version": settings.embedding_version,
            "sample_rate": settings.rag_event_pilot_sample_rate,
            "hit_count": len(hits),
            "document_ids": sorted({hit.document_id for hit in hits}),
        },
    )
    return hits


async def process_events_async(
    uow: UnitOfWork,
    ai: Gateway | InvestmentResearchAgent,
    *,
    events: list[ExtractedEvent],
    security_id: str,
    actor: Actor,
    thresholds: RuleThresholds,
    current_event_segments: list[DocumentSegmentRecord],
    document_id: str = "",
    locator_by_event: dict[str, str] | None = None,
    document_title: str | None = None,
    source_visibility_label: str = "内部",
    source_url: str | None = None,
    rag_settings: Settings | None = None,
) -> ChangeResult:
    """处理一批事件，产出候选证据与状态建议。"""
    kept, sources = dedupe_events(events)
    recalled = thesis.recall_candidates(uow, security_id=security_id, actor=actor)
    graph_corpus = (
        build_graph_rag_corpus(
            uow,
            thesis_ids=[record.thesis_id for record, _ in recalled],
        )
        if rag_settings and rag_settings.rag_graph_enabled and recalled
        else None
    )
    recalled, recall_traces = _rank_candidates(
        recalled,
        events=kept,
        graph_corpus=graph_corpus,
        settings=rag_settings,
    )
    retrieval_mode = (
        "text+graph"
        if graph_corpus and rag_settings and rag_settings.rag_event_pilot_enabled
        else "graph"
        if graph_corpus
        else "text"
        if rag_settings and rag_settings.rag_event_pilot_enabled
        else "baseline"
    )
    candidates: list[EvidenceRecord] = []
    deferred: list[tuple[str, str]] = []
    suggestions: list[tuple[str, StatusSuggestion]] = []

    rag_contexts = {
        event.event_id: _rag_context(
            uow,
            event=event,
            security_id=security_id,
            actor=actor,
            settings=rag_settings,
        )
        for event in kept
    }
    if retrieval_mode != "baseline":
        for event in kept:
            audit.record(
                uow.audit,
                actor=actor.user_id,
                action="RAG候选逻辑排序",
                object_type="event",
                object_id=event.event_id,
                detail={
                    "retrieval_mode": retrieval_mode,
                    "graph_snapshot_id": (
                        graph_corpus.snapshot.snapshot_id if graph_corpus else None
                    ),
                    "candidates": [trace.to_dict() for trace in recall_traces],
                },
            )
    retriever = KeywordRetriever()
    segments_by_locator = index_current_event_segments(current_event_segments)
    event_inputs: dict[str, EventAgentInputs] = {}
    current_event_evidence: list[RetrievalDocument] = []
    historical_rag_context: list[RetrievalDocument] = []
    for event in kept:
        try:
            inputs = build_event_agent_inputs(
                event=event,
                security_id=security_id,
                segments_by_locator=segments_by_locator,
                locator_override=(locator_by_event or {}).get(event.event_id),
                visibility_label=source_visibility_label,
                source=document_title or event.document_id,
            )
        except EventEvidenceUnavailable as exc:
            deferred.append((event.event_id, str(exc)))
            continue
        event_inputs[event.event_id] = inputs
        current_event_evidence.append(inputs.current_event_evidence)
        historical_rag_context.extend(
            build_historical_rag_context(
                security_id=security_id,
                hits=rag_contexts[event.event_id],
            )
        )
    agent_retrieval_documents = [*historical_rag_context, *current_event_evidence]
    if isinstance(ai, InvestmentResearchAgent):
        runtime = ai
        if graph_corpus and rag_settings:
            runtime.logic_change.retriever = build_graph_retriever_from_corpus(
                graph_corpus,
                text_retriever=runtime.logic_change.retriever,
                text_weight=rag_settings.rag_graph_text_weight,
                graph_weight=rag_settings.rag_graph_relation_weight,
                max_hops=rag_settings.rag_graph_max_hops,
                assist_only=rag_settings.rag_graph_assist_only,
            )
        runtime.logic_change.retriever.add(agent_retrieval_documents)
    else:
        active_retriever = (
            build_graph_retriever_from_corpus(
                graph_corpus,
                text_retriever=retriever,
                text_weight=rag_settings.rag_graph_text_weight,
                graph_weight=rag_settings.rag_graph_relation_weight,
                max_hops=rag_settings.rag_graph_max_hops,
                assist_only=rag_settings.rag_graph_assist_only,
            )
            if graph_corpus and rag_settings
            else retriever
        )
        active_retriever.add(agent_retrieval_documents)
        runtime = InvestmentResearchAgent.build(ai, retriever=active_retriever)

    for record, hypotheses in recalled:
        touched = False
        hypothesis_inputs = tuple(
            build_hypothesis_input(
                thesis_record=record,
                hypothesis=hypothesis,
                mappings=uow.thesis.list_mappings(hypothesis.hypothesis_id),
            )
            for hypothesis in hypotheses
        )
        analyzable = [
            (event, event_inputs[event.event_id])
            for event in kept
            if event.event_id in event_inputs
        ]
        if not hypothesis_inputs:
            deferred.extend(
                (event.event_id, "候选逻辑下没有可分析假设，转人工判断") for event, _ in analyzable
            )
            continue

        # 同一份资料的多个事件与该逻辑的全部假设在一个模型请求内判断。
        executions = await runtime.analyze_events_async(
            tuple(inputs.event for _, inputs in analyzable),
            hypothesis_inputs,
            allowed_visibility=actor.document_labels,
            top_k=(rag_settings.rag_event_pilot_limit if rag_settings else 3),
            idempotency_key=f"document:{document_id}:thesis:{record.thesis_id}",
        )
        if executions and all(execution.degraded_reason for execution in executions):
            raise ModelUnavailable("批量事件影响分析输出不符合契约", retryable=False)

        for (event, inputs), execution in zip(analyzable, executions, strict=True):
            analysis_result = to_backend_analysis_result(execution)
            if analysis_result.retryable:
                raise ModelUnavailable(
                    analysis_result.degraded_reason or "Runtime 暂时不可用",
                    retryable=True,
                )
            if not analysis_result.impacts:
                deferred.append((event.event_id, "Runtime 未生成候选影响，转人工"))
                continue
            runtime_impacts = (
                {item.candidate.hypothesis_id: item for item in execution.result.impacts}
                if isinstance(execution.result, AgentRunResult)
                else {}
            )
            for impact in analysis_result.impacts:
                hypothesis_id = impact.hypothesis_id

                audit.record_model_call(
                    uow.audit,
                    actor=actor.user_id,
                    object_type="event",
                    object_id=event.event_id,
                    model_version=impact.model_version or "",
                    prompt_version=impact.prompt_version or "",
                    ai_status=impact.ai_status.value,
                    model_metadata=impact.model_metadata,
                )

                if impact.ai_status is AiStatus.PARSE_FAILED:
                    deferred.append((event.event_id, "模型输出不合契约，转人工"))
                    continue

                annotated_target = event.hypothesis_id == hypothesis_id
                direction = (
                    event.impact_direction
                    if annotated_target and event.impact_direction is not None
                    else impact.impact_direction
                )
                if direction is ImpactDirection.IRRELEVANT:
                    deferred.append((event.event_id, "模型判定与该假设不相关，不进入证据链"))
                    continue
                score = (
                    event.strength_score
                    if annotated_target and event.strength_score is not None
                    else impact.strength_score
                )
                bucket = to_strength_bucket(score)

                evidence_id = _stable_id("EVD", event.event_id, impact.thesis_id, hypothesis_id)
                if uow.evidence.get(evidence_id) is not None:
                    deferred.append((event.event_id, "该事件与假设已生成候选证据，跳过重复提醒"))
                    continue

                candidate = EvidenceRecord(
                    evidence_id=evidence_id,
                    thesis_id=impact.thesis_id,
                    hypothesis_id=hypothesis_id,
                    evidence_type=event.event_type,
                    direction=direction,
                    evidence_locator=inputs.event.evidence_locator,
                    event_id=event.event_id,
                    strength=bucket.value if bucket is not None else None,
                    strength_score=score,
                    horizon=(
                        event.horizon if annotated_target and event.horizon else impact.horizon
                    ),
                    ai_status=impact.ai_status.value,
                    ai_confidence=impact.confidence,
                    model_version=impact.model_version,
                    prompt_version=impact.prompt_version,
                    confirmation_status=ConfirmationStatus.PENDING,
                    source_visibility_label=source_visibility_label,
                    security_id=security_id,
                    fact_excerpt=event.summary,
                    source_document_id=event.document_id,
                    source_document_title=document_title or event.document_id,
                    disclosed_at=event.disclosure_time,
                    occurred_at=event.occurred_on,
                    source_url=source_url,
                    retrieval_trace=(
                        _retrieval_trace(
                            runtime_impacts[hypothesis_id].retrieval,
                            locator=inputs.event.evidence_locator,
                        )
                        if hypothesis_id in runtime_impacts
                        else None
                    ),
                )
                evidence_service.create_candidate(uow, record=candidate, actor=actor.user_id)
                relation_service.create_candidate(
                    uow,
                    evidence_id=candidate.evidence_id,
                    thesis_id=impact.thesis_id,
                    hypothesis_id=hypothesis_id,
                    direction=direction,
                    strength=candidate.strength,
                    reason="上传资料自动召回候选关联，待逻辑负责人核验",
                    actor=actor.user_id,
                )
                candidates.append(candidate)
                touched = True

                if impact.ai_status is AiStatus.LOW_CONFIDENCE:
                    # FR-R-007：低置信进人工队列，不升级提醒
                    deferred.append((event.event_id, "低置信，进人工复核队列，不触发风险提醒"))

        if touched:
            # 新资料先完成事件→假设关联，再用资料首次公开日作为 as-of 核对指标；
            # 不能让晚于该资料的财务数据反向影响当时的建议。
            as_of = max(event.disclosure_time.date() for event in kept)
            suggestion = status_service.compute_suggestion(
                uow,
                thesis=record,
                hypotheses=list(hypotheses),
                thresholds=thresholds,
                today=as_of,
            )
            status_service.record_suggestion(
                uow, thesis=record, suggestion=suggestion, actor=actor.user_id
            )
            suggestions.append((record.thesis_id, suggestion))

    for event in kept:
        merged = sources.get(event.fingerprint, [])
        if len(merged) > 1:
            deferred.append((event.event_id, f"合并 {len(merged)} 个来源，不重复提醒"))

    return ChangeResult(
        document_id=document_id,
        candidates=candidates,
        suggestions=suggestions,
        deferred=deferred,
        matched_theses=[r.thesis_id for r, _ in recalled],
        retrieval_mode=retrieval_mode,
        recall_traces=recall_traces,
        graph_snapshot_id=(graph_corpus.snapshot.snapshot_id if graph_corpus else None),
    )


def process_events(
    uow: UnitOfWork,
    ai: Gateway | InvestmentResearchAgent,
    **kwargs: object,
) -> ChangeResult:
    """同步兼容入口；worker 使用 ``process_events_async``。"""
    return asyncio.run(process_events_async(uow, ai, **kwargs))  # type: ignore[arg-type]
