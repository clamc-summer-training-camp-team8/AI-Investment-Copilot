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

from dataclasses import dataclass
from decimal import Decimal

from app.ai.agents import AgentEvent, CandidateHypothesis
from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.runtime import InvestmentResearchAgent
from app.calc.rules import StatusSuggestion
from app.core.config import RuleThresholds
from app.core.enums import AiStatus, ConfirmationStatus, ImpactDirection
from app.ingest.events import ExtractedEvent, dedupe_events, to_strength_bucket
from app.services import audit, thesis
from app.services import evidence as evidence_service
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
        score = sum(
            1
            for token in ("订单", "收入", "毛利率", "装机", "需求", "政策")
            if token in statement and token in event.summary
        )
        if score > best_score:
            best, best_score = str(getattr(hypothesis, "hypothesis_id", "")), score
    return best


def process_events(
    uow: UnitOfWork,
    ai: Gateway | InvestmentResearchAgent,
    *,
    events: list[ExtractedEvent],
    security_id: str,
    actor: Actor,
    thresholds: RuleThresholds,
    document_id: str = "",
    locator_by_event: dict[str, str] | None = None,
) -> ChangeResult:
    """处理一批事件，产出候选证据与状态建议。"""
    kept, sources = dedupe_events(events)
    recalled = thesis.recall_candidates(uow, security_id=security_id, actor=actor)
    runtime = (
        ai
        if isinstance(ai, InvestmentResearchAgent)
        else InvestmentResearchAgent.build(ai)
    )

    candidates: list[EvidenceRecord] = []
    deferred: list[tuple[str, str]] = []
    suggestions: list[tuple[str, StatusSuggestion]] = []

    for record, hypotheses in recalled:
        touched = False
        for event in kept:
            hypothesis_id = _pick_hypothesis(event, list(hypotheses))
            if hypothesis_id is None:
                deferred.append((event.event_id, "未能落到具体假设，转人工判断"))
                continue
            if hypothesis_id not in {str(getattr(h, "hypothesis_id", "")) for h in hypotheses}:
                continue

            locator = (locator_by_event or {}).get(event.event_id) or event.evidence_locator
            if locator is None:
                # 没有引用定位的结论不得进入正式证据链（DQ-005）
                deferred.append((event.event_id, "缺少引用定位，无法进入证据链"))
                continue

            hypothesis = next(
                item
                for item in hypotheses
                if str(getattr(item, "hypothesis_id", "")) == hypothesis_id
            )
            execution = runtime.analyze_event(
                AgentEvent(
                    event_id=event.event_id,
                    document_id=event.document_id,
                    security_id=security_id,
                    segment_locator=locator,
                    segment_text=event.summary,
                    disclosure_time=event.disclosure_time,
                    event_type=event.event_type,
                    occurred_on=event.occurred_on,
                ),
                [
                    CandidateHypothesis(
                        thesis_id=record.thesis_id,
                        hypothesis_id=hypothesis_id,
                        statement=str(getattr(hypothesis, "statement", "")),
                        thesis_context=str(getattr(record, "core_view", "")) or None,
                        hypothesis_context={
                            "hypothesis_type": getattr(hypothesis, "hypothesis_type", None),
                            "importance": getattr(
                                getattr(hypothesis, "importance", None), "value", None
                            ),
                            "expected_direction": getattr(
                                getattr(hypothesis, "expected_direction", None), "value", None
                            ),
                            "invalidation_rule": getattr(
                                hypothesis, "invalidation_rule", None
                            ),
                            "metrics": [
                                {
                                    "metric_id": getattr(mapping, "metric_id", None),
                                    "unit": getattr(mapping, "unit", None),
                                }
                                for mapping in uow.thesis.list_mappings(hypothesis_id)
                            ],
                        },
                    )
                ],
                idempotency_key=(
                    f"event:{event.event_id}:thesis:{record.thesis_id}:hypothesis:{hypothesis_id}"
                ),
            )
            if execution.retryable:
                raise ModelUnavailable(
                    execution.degraded_reason or "Runtime 暂时不可用",
                    retryable=True,
                )
            if execution.result is None or not execution.result.impacts:
                deferred.append((event.event_id, "Runtime 未生成候选影响，转人工"))
                continue
            outcome = execution.result.impacts[0].outcome

            audit.record_model_call(
                uow.audit,
                actor=actor.user_id,
                object_type="event",
                object_id=event.event_id,
                model_version=str(outcome.payload.get("model_version", "")),
                prompt_version=str(outcome.payload.get("prompt_version", "")),
                ai_status=outcome.ai_status.value,
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
            score = event.strength_score
            if score is None:
                score = _dec(signal.get("strength"))
            bucket = to_strength_bucket(score)

            candidate = EvidenceRecord(
                evidence_id=f"EVD-{event.event_id}-{hypothesis_id}",
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
            )
            evidence_service.create_candidate(uow, record=candidate, actor=actor.user_id)
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


def _dec(value: object) -> Decimal | None:
    """转 Decimal。走字符串避免 float 二进制残留进入数据库。"""
    if value is None:
        return None
    return Decimal(str(value))
