"""将日内候选关系收口为一条主投资逻辑变化候选。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

from app.ai.gateway import Gateway
from app.core.domain import EvidenceRecord, LogicChangeDigestRecord, UnitOfWork
from app.core.enums import AiStatus, ConfirmationStatus
from app.core.timeutil import business_date
from app.services import audit

MAX_CANDIDATES_PER_RUN = 80


@dataclass(frozen=True)
class ConsolidationResult:
    thesis_id: str
    digest_id: str | None
    candidate_count: int
    ai_status: str
    skipped_reason: str | None = None


async def consolidate_daily_logic_change(
    uow: UnitOfWork,
    *,
    gateway: Gateway,
    security_id: str,
    thesis_id: str,
    as_of: date,
    actor_id: str,
) -> ConsolidationResult:
    """归并已提交的候选关系，并覆盖同一日同一逻辑的旧归并稿。

    每次新资料分析完成后重跑一次。因此它读取的是该业务日的全部候选，而不是只
    读取触发本次任务的单篇资料；原始 Evidence / EvidenceRelation 不会被修改。
    """
    thesis = uow.thesis.get(thesis_id)
    if thesis is None or thesis.security_id != security_id:
        return ConsolidationResult(thesis_id, None, 0, AiStatus.PARSE_FAILED.value, "逻辑不存在")

    records = _daily_candidates(uow.evidence.list_for_thesis(thesis_id), security_id, as_of)
    if not records:
        return ConsolidationResult(thesis_id, None, 0, AiStatus.CANDIDATE.value, "当日无候选关系")

    hypotheses = uow.thesis.list_hypotheses(thesis_id)
    hypothesis_by_id = {item.hypothesis_id: item for item in hypotheses}
    evidence_input = [_evidence_input(item, hypothesis_by_id) for item in records]
    hypothesis_metrics = {
        item.hypothesis_id: _hypothesis_metrics(uow, item.hypothesis_id) for item in hypotheses
    }
    outcome = await gateway.logic_change_consolidation_async(
        security_id=security_id,
        thesis_id=thesis_id,
        business_date=as_of.isoformat(),
        thesis_core_view=thesis.core_view,
        hypotheses=[
            {
                "hypothesis_id": item.hypothesis_id,
                "statement": item.statement,
                "importance": item.importance.value,
                "metrics": hypothesis_metrics[item.hypothesis_id],
            }
            for item in hypotheses
        ],
        candidate_evidence=evidence_input,
    )
    if not outcome.usable:
        return ConsolidationResult(
            thesis_id,
            None,
            len(records),
            outcome.ai_status.value,
            "归并模型输出未通过契约，已保留原始候选供人工处理",
        )

    payload = outcome.payload
    allowed_ids = {item.evidence_id for item in records}
    allowed_hypotheses = set(hypothesis_by_id)
    citations = _allowed_ids(payload.get("citations"), allowed_ids)
    allowed_metrics = {
        hypothesis_id: {str(metric["metric_id"]) for metric in metrics}
        for hypothesis_id, metrics in hypothesis_metrics.items()
    }
    impacts = _sanitize_impacts(
        payload.get("hypothesis_impacts"), allowed_ids, allowed_hypotheses, allowed_metrics
    )
    if not citations:
        citations = [item.evidence_id for item in records[:12]]
    if not impacts:
        impacts = _fallback_impacts(records)
    digest_id = _digest_id(security_id, thesis_id, as_of)
    generated_at = _parse_datetime(payload.get("generated_at"))
    digest = uow.logic_change_digests.upsert(
        LogicChangeDigestRecord(
            digest_id=digest_id,
            security_id=security_id,
            thesis_id=thesis_id,
            business_date=as_of,
            overall_direction=str(payload["overall_direction"]),
            summary=str(payload["summary"]).strip(),
            hypothesis_impacts=impacts,
            open_questions=[
                str(item).strip() for item in payload.get("open_questions", []) if str(item).strip()
            ],
            citations=citations,
            source_document_ids=sorted(
                {item.source_document_id for item in records if item.source_document_id}
            ),
            candidate_count=len(records),
            confidence=Decimal(str(payload.get("confidence", 0))),
            ai_status=outcome.ai_status.value,
            confirmation_status=ConfirmationStatus.PENDING,
            model_version=str(payload.get("model_version") or ""),
            prompt_version=str(payload.get("prompt_version") or ""),
            generated_at=generated_at,
        )
    )
    audit.record_model_call(
        uow.audit,
        actor=actor_id,
        object_type="logic_change_digest",
        object_id=digest.digest_id,
        model_version=digest.model_version or "",
        prompt_version=digest.prompt_version or "",
        ai_status=digest.ai_status,
        model_metadata=(
            dict(payload["model_metadata"])
            if isinstance(payload.get("model_metadata"), dict)
            else None
        ),
    )
    return ConsolidationResult(thesis_id, digest.digest_id, len(records), outcome.ai_status.value)


def _daily_candidates(
    records: list[EvidenceRecord], security_id: str, as_of: date
) -> list[EvidenceRecord]:
    active = [
        item
        for item in records
        if item.security_id == security_id
        and item.ingested_at is not None
        and business_date(item.ingested_at) == as_of
        and item.confirmation_status
        not in {ConfirmationStatus.REJECTED, ConfirmationStatus.DEACTIVATED}
    ]
    # 同一关系多次重跑时选择最新一条，避免输入被重复证据放大。
    deduped = {item.evidence_id: item for item in active}
    return sorted(
        deduped.values(),
        key=lambda item: (
            -(float(item.ai_confidence) if item.ai_confidence is not None else 0),
            item.evidence_id,
        ),
    )[:MAX_CANDIDATES_PER_RUN]


def _evidence_input(item: EvidenceRecord, hypotheses: dict[str, Any]) -> dict[str, Any]:
    hypothesis = hypotheses.get(item.hypothesis_id)
    return {
        "evidence_id": item.evidence_id,
        "hypothesis_id": item.hypothesis_id,
        "hypothesis": hypothesis.statement if hypothesis else "",
        "direction": item.direction.value,
        "strength": item.strength,
        "confidence": float(item.ai_confidence) if item.ai_confidence is not None else None,
        "fact": (item.fact_excerpt or "")[:800],
        "source_document_id": item.source_document_id,
        "source_title": item.source_document_title,
        "disclosed_at": item.disclosed_at.isoformat() if item.disclosed_at else None,
        "evidence_locator": item.evidence_locator,
    }


def _hypothesis_metrics(uow: UnitOfWork, hypothesis_id: str) -> list[dict[str, object]]:
    """将研究员已维护的指标口径传给归并模型，限制其不得臆造观察指标。"""
    result: list[dict[str, object]] = []
    for mapping in uow.thesis.list_mappings(hypothesis_id):
        definition = uow.metrics.get(mapping.metric_id, mapping.metric_version)
        result.append(
            {
                "metric_id": mapping.metric_id,
                "name": definition.name if definition else mapping.metric_id,
                "unit": definition.unit if definition else "",
                "expected_direction": mapping.expected_direction.value,
                "expected_value": str(mapping.expected_value)
                if mapping.expected_value is not None
                else None,
                "invalidation_threshold": str(mapping.invalidation_threshold)
                if mapping.invalidation_threshold is not None
                else None,
            }
        )
    return result


def _allowed_ids(value: object, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item) in allowed))[:12]


def _sanitize_impacts(
    value: object,
    allowed_ids: set[str],
    allowed_hypotheses: set[str],
    allowed_metrics: dict[str, set[str]],
) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        hypothesis_id = str(item.get("hypothesis_id") or "")
        evidence_ids = _allowed_ids(item.get("evidence_ids"), allowed_ids)
        if hypothesis_id not in allowed_hypotheses or not evidence_ids:
            continue
        related_metric_ids = (
            [
                str(metric_id)
                for metric_id in item.get("related_metric_ids", [])
                if str(metric_id) in allowed_metrics.get(hypothesis_id, set())
            ]
            if isinstance(item.get("related_metric_ids"), list)
            else []
        )
        direction = str(item.get("direction") or "待观察")
        rationale = str(item.get("rationale") or "待研究员核验。")[:600]
        business_impact = str(item.get("business_impact") or "尚不能确认具体经营含义。")[:400]
        cleaned.append(
            {
                "hypothesis_id": hypothesis_id,
                "direction": direction,
                "strength": str(item.get("strength") or "中"),
                "strength_reason": str(
                    item.get("strength_reason") or "模型未说明强度依据，待研究员复核。"
                )[:400],
                "rationale": rationale,
                "business_impact": business_impact,
                "indicator_outlook": str(
                    item.get("indicator_outlook") or "需结合后续可观察数据验证。"
                )[:400],
                "impact_layer": str(item.get("impact_layer") or "市场预期"),
                "directness": str(item.get("directness") or "合理推测"),
                "transmission_status": str(item.get("transmission_status") or "尚待验证"),
                "hypothesis_effect": str(item.get("hypothesis_effect") or "增加不确定性"),
                "presentation": str(item.get("presentation") or "证据不足"),
                "paths": _sanitize_paths(
                    item.get("paths"),
                    allowed_ids,
                    evidence_ids,
                    direction=direction,
                    rationale=rationale,
                    business_impact=business_impact,
                ),
                "related_metric_ids": list(dict.fromkeys(related_metric_ids))[:6],
                "evidence_ids": evidence_ids,
            }
        )
    return cleaned[:12]


def _sanitize_paths(
    value: object,
    allowed_ids: set[str],
    fallback_evidence_ids: list[str],
    *,
    direction: str,
    rationale: str,
    business_impact: str,
) -> list[dict[str, object]]:
    """只保留能回指真实证据的传导路径，避免展示无法核验的模型描述。"""
    paths: list[dict[str, object]] = []
    if isinstance(value, list):
        for item in value[:4]:
            if not isinstance(item, dict):
                continue
            evidence_ids = _allowed_ids(item.get("evidence_ids"), allowed_ids)
            if not evidence_ids:
                continue
            paths.append(
                {
                    "direction": str(item.get("direction") or "中性"),
                    "label": str(item.get("label") or "待核验传导路径")[:120],
                    "mechanism": str(item.get("mechanism") or "尚未形成可解释传导。")[:500],
                    "evidence_ids": evidence_ids,
                }
            )
    if paths:
        return paths
    fallback_direction = direction if direction in {"支持", "冲突", "中性"} else "中性"
    has_business_reading = not business_impact.startswith("尚不能确认")
    return [
        {
            "direction": fallback_direction,
            "label": "AI 候选传导",
            "mechanism": (
                f"{rationale} {'经营含义：' + business_impact if has_business_reading else '尚缺少可确认的经营传导，需补充直接证据。'}"
            )[:500],
            "evidence_ids": fallback_evidence_ids[:6],
        }
    ]


def _fallback_impacts(records: list[EvidenceRecord]) -> list[dict[str, object]]:
    grouped: dict[str, list[EvidenceRecord]] = {}
    for item in records:
        grouped.setdefault(item.hypothesis_id, []).append(item)
    result: list[dict[str, object]] = []
    for hypothesis_id, items in grouped.items():
        directions = {item.direction.value for item in items}
        direction = (
            "分歧"
            if {"支持", "冲突"}.issubset(directions)
            else "冲突"
            if "冲突" in directions
            else "支持"
            if "支持" in directions
            else "待观察"
        )
        result.append(
            {
                "hypothesis_id": hypothesis_id,
                "direction": direction,
                "strength": "中",
                "strength_reason": "模型未返回可用强度判断，当前仅按候选关系数量归并，需研究员复核。",
                "rationale": "模型未返回可用的假设级引用，保留原始候选待研究员核验。",
                "business_impact": "尚不能确认具体经营含义。",
                "indicator_outlook": "需结合后续可观察数据验证。",
                "impact_layer": "市场预期",
                "directness": "证据不足",
                "transmission_status": "尚待验证",
                "hypothesis_effect": "增加不确定性",
                "presentation": "证据不足",
                "paths": [
                    {
                        "direction": "中性",
                        "label": "原子候选待模型归并",
                        "mechanism": "当前只有原子证据关系，尚未形成假设级传导分析；应重新触发归并模型，而非据此判断影响方向。",
                        "evidence_ids": [item.evidence_id for item in items[:6]],
                    }
                ],
                "related_metric_ids": [],
                "evidence_ids": [item.evidence_id for item in items[:12]],
            }
        )
    return result[:12]


def _digest_id(security_id: str, thesis_id: str, as_of: date) -> str:
    value = f"{security_id}|{thesis_id}|{as_of.isoformat()}".encode()
    return f"LCD-{sha256(value).hexdigest()[:24]}"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
