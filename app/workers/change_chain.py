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

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from app.ai.gateway import Gateway
from app.calc.rules import StatusSuggestion
from app.core.config import RuleThresholds, Settings
from app.core.enums import AiStatus, ConfirmationStatus, ImpactDirection
from app.ingest.events import ExtractedEvent, dedupe_events, to_strength_bucket
from app.services import assets as asset_service
from app.services import audit, thesis
from app.services import evidence as evidence_service
from app.services import relation as relation_service
from app.services import status as status_service
from app.services.permission import Actor
from app.services.ports import EvidenceRecord, UnitOfWork


@dataclass
class ChangeResult:
    """一条资料的变化处理结果。"""

    document_id: str
    candidates: list[EvidenceRecord]
    suggestions: list[tuple[str, StatusSuggestion]]
    deferred: list[tuple[str, str]]
    matched_theses: list[str]


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


def _rag_context(
    uow: UnitOfWork,
    *,
    event: ExtractedEvent,
    security_id: str,
    actor: Actor,
    settings: Settings | None,
) -> list[tuple[str, str]]:
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
    return [(hit.locator, hit.content) for hit in hits]


def process_events(
    uow: UnitOfWork,
    gateway: Gateway,
    *,
    events: list[ExtractedEvent],
    security_id: str,
    actor: Actor,
    thresholds: RuleThresholds,
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

    for record, hypotheses in recalled:
        touched = False
        for event in kept:
            hypothesis_id = _pick_hypothesis(event, list(hypotheses))
            if hypothesis_id is None:
                deferred.append((event.event_id, "未能落到具体假设，转人工判断"))
                continue
            if hypothesis_id not in {str(getattr(h, "hypothesis_id", "")) for h in hypotheses}:
                continue
            target_hypothesis = next(
                hypothesis
                for hypothesis in hypotheses
                if str(getattr(hypothesis, "hypothesis_id", "")) == hypothesis_id
            )
            mappings = uow.thesis.list_mappings(hypothesis_id)
            hypothesis_context: dict[str, object] = {
                "statement": target_hypothesis.statement,
                "hypothesis_type": target_hypothesis.hypothesis_type,
                "importance": target_hypothesis.importance.value,
                "expected_direction": (
                    target_hypothesis.expected_direction.value
                    if target_hypothesis.expected_direction is not None
                    else None
                ),
                "invalidation_rule": target_hypothesis.invalidation_rule,
                "metrics": [
                    {
                        "metric_id": mapping.metric_id,
                        "expected_direction": mapping.expected_direction.value,
                        "expected_value": (
                            str(mapping.expected_value)
                            if mapping.expected_value is not None
                            else None
                        ),
                        "invalidation_threshold": (
                            str(mapping.invalidation_threshold)
                            if mapping.invalidation_threshold is not None
                            else None
                        ),
                    }
                    for mapping in mappings
                ],
            }

            locator = (locator_by_event or {}).get(event.event_id) or event.evidence_locator
            if locator is None:
                # 没有引用定位的结论不得进入正式证据链（DQ-005）
                deferred.append((event.event_id, "缺少引用定位，无法进入证据链"))
                continue

            outcome = gateway.event_impact(
                document_id=event.document_id,
                security_id=security_id,
                segment_locator=locator,
                segment_text=event.summary,
                disclosure_time=_iso(event.disclosure_time),
                thesis_id=record.thesis_id,
                hypothesis_id=hypothesis_id,
                thesis_context=record.core_view,
                hypothesis_context=hypothesis_context,
                retrieval_context=rag_contexts[event.event_id],
                event_type=event.event_type,
                occurred_on=event.occurred_on.isoformat() if event.occurred_on else None,
            )

            audit.record_model_call(
                uow.audit,
                actor=actor.user_id,
                object_type="event",
                object_id=event.event_id,
                model_version=str(outcome.payload.get("model_version", "")),
                prompt_version=str(outcome.payload.get("prompt_version", "")),
                ai_status=outcome.ai_status.value,
                model_metadata=(
                    outcome.payload.get("model_metadata")
                    if isinstance(outcome.payload.get("model_metadata"), dict)
                    else None
                ),
            )

            if outcome.ai_status is AiStatus.PARSE_FAILED:
                deferred.append((event.event_id, "模型输出不合契约，转人工"))
                continue

            signal = outcome.payload["signal"]
            if not isinstance(signal, dict):
                deferred.append((event.event_id, "模型输出缺少 signal 段，转人工"))
                continue

            # 人工标注的方向优先于模型判断：标注是金标（标注规范 §10）
            direction = event.impact_direction or ImpactDirection(
                str(signal.get("impact_direction") or ImpactDirection.NEUTRAL.value)
            )
            if direction is ImpactDirection.IRRELEVANT:
                deferred.append((event.event_id, "模型判定与该假设不相关，不进入证据链"))
                continue
            score = event.strength_score
            if score is None:
                score = _dec(signal.get("strength"))
            bucket = to_strength_bucket(score)

            evidence_id = _stable_id("EVD", event.event_id, record.thesis_id, hypothesis_id)
            if uow.evidence.get(evidence_id) is not None:
                deferred.append((event.event_id, "该事件与假设已生成候选证据，跳过重复提醒"))
                continue

            candidate = EvidenceRecord(
                evidence_id=evidence_id,
                thesis_id=record.thesis_id,
                hypothesis_id=hypothesis_id,
                evidence_type=event.event_type,
                direction=direction,
                evidence_locator=locator,
                event_id=event.event_id,
                strength=bucket.value if bucket is not None else None,
                strength_score=score,
                horizon=event.horizon or str(signal.get("horizon") or "") or None,
                ai_status=outcome.ai_status.value,
                ai_confidence=_dec(signal.get("confidence")),
                model_version=str(outcome.payload.get("model_version", "")),
                prompt_version=str(outcome.payload.get("prompt_version", "")),
                confirmation_status=ConfirmationStatus.PENDING,
                source_visibility_label=source_visibility_label,
                security_id=security_id,
                fact_excerpt=event.summary,
                source_document_id=event.document_id,
                source_document_title=document_title or event.document_id,
                disclosed_at=event.disclosure_time,
                occurred_at=event.occurred_on,
                source_url=source_url,
            )
            evidence_service.create_candidate(uow, record=candidate, actor=actor.user_id)
            relation_service.create_candidate(
                uow,
                evidence_id=candidate.evidence_id,
                thesis_id=record.thesis_id,
                hypothesis_id=hypothesis_id,
                direction=direction,
                strength=candidate.strength,
                reason="上传资料自动召回候选关联，待逻辑负责人核验",
                actor=actor.user_id,
            )
            candidates.append(candidate)
            touched = True

            if outcome.ai_status is AiStatus.LOW_CONFIDENCE:
                # FR-R-007：低置信进人工队列，不升级提醒
                deferred.append((event.event_id, "低置信，进人工复核队列，不触发风险提醒"))

        if touched:
            suggestion = status_service.compute_suggestion(
                uow, thesis=record, hypotheses=list(hypotheses), thresholds=thresholds
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
    )


def _iso(value: datetime) -> str:
    return value.isoformat()


def _dec(value: object) -> Decimal | None:
    """转 Decimal。走字符串避免 float 二进制残留进入数据库。"""
    if value is None:
        return None
    return Decimal(str(value))
