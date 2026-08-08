"""逻辑卡片编排（FR-T-001 ~ FR-T-007）。

草稿由 AI 或人工输入生成，**发布必须由人工完成**并补齐研究员专属字段：时间范围、
原始预期、失效条件和负责人（PRD 7.1 第 3 步）。这几项 AI 不许代填。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from app.core.enums import Importance, ThesisStatus, Visibility
from app.services import audit, permission, version
from app.services.errors import EntityAmbiguous, HumanGateRequired, ValidationFailed
from app.services.permission import Actor
from app.services.ports import (
    HypothesisRecord,
    MetricMappingRecord,
    ThesisRecord,
    UnitOfWork,
)

TITLE_MAX = 40
CORE_VIEW_MAX = 200


def create_draft(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    draft: dict[str, Any],
    actor: Actor,
    security_candidates: list[dict[str, str]] | None = None,
) -> ThesisRecord:
    """把 AI 草稿落成卡片草稿。

    实体歧义时抛 EntityAmbiguous 要求用户选择，**不自动绑定**（PRD 7.4）：
    绑错公司的代价远大于让用户多点一次。
    """
    if security_candidates and len(security_candidates) > 1:
        raise EntityAmbiguous("识别到多个候选主体，请选择", security_candidates)

    security_id = draft.get("security_id")
    if not security_id:
        raise ValidationFailed("缺少投资对象")

    title = str(draft.get("title") or "").strip()
    core_view = str(draft.get("core_view") or "").strip()
    if not title or not core_view:
        raise ValidationFailed("标题与核心观点不可为空")
    if len(title) > TITLE_MAX:
        raise ValidationFailed(f"标题不得超过 {TITLE_MAX} 字（PRD 4.3）")
    if len(core_view) > CORE_VIEW_MAX:
        raise ValidationFailed(f"核心观点不得超过 {CORE_VIEW_MAX} 字（PRD 4.3）")

    hypotheses = draft.get("hypotheses") or []
    if not 2 <= len(hypotheses) <= 5:
        raise ValidationFailed("关键假设须为 2 至 5 条（PRD 5.1）")

    record = ThesisRecord(
        thesis_id=thesis_id,
        security_id=str(security_id),
        title=title,
        # 方向由人工确认（PRD 4.3 生成方式为「人工」），草稿阶段先落观察。
        direction=str(draft.get("direction") or "观察"),
        core_view=core_view,
        established_on=date.today(),
        owner=actor.user_id,
        status=ThesisStatus.DRAFT,
        visibility=Visibility.TEAM,
        source_document_id=draft.get("source_document_id"),
    )
    uow.thesis.add(record)

    for index, item in enumerate(hypotheses, start=1):
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=f"{thesis_id}-H{index}",
                thesis_id=thesis_id,
                statement=str(item["statement"]),
                hypothesis_type=str(item.get("hypothesis_type") or "其他"),
                importance=Importance(item.get("importance") or "辅助"),
            )
        )

    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CREATE,
        object_type="thesis",
        object_id=thesis_id,
        detail={"source": "ai_draft", "hypothesis_count": len(hypotheses)},
        model_version=draft.get("model_version"),
    )
    return record


def set_expectations(
    uow: UnitOfWork,
    *,
    hypothesis_id: str,
    mapping: MetricMappingRecord,
    actor: Actor,
) -> MetricMappingRecord:
    """录入研究员预期与失效阈值。

    这两项只能由人工填写（PRD 10.1 限制、GAP-002 要求记录来源），因此强制要求
    expectation_source 非空——没有来源的预期无法追溯，预期差也就失去意义。
    """
    if mapping.expected_value is None and mapping.invalidation_threshold is None:
        raise ValidationFailed("必须至少给出预期值或失效阈值")
    if not (mapping.expectation_source or "").strip():
        raise ValidationFailed("必须记录预期来源（GAP-002）")

    uow.thesis.add_mapping(replace(mapping, hypothesis_id=hypothesis_id))
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.EDIT,
        object_type="hypothesis_metric_map",
        object_id=mapping.mapping_id,
        detail={
            "expected_value": str(mapping.expected_value),
            "invalidation_threshold": str(mapping.invalidation_threshold),
            "expectation_source": mapping.expectation_source,
        },
    )
    return mapping


def publish(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    actor: Actor,
    direction: str,
    horizon_end_on: date,
    next_review_at: date,
    invalidation_require_all: bool = True,
) -> ThesisRecord:
    """发布，生成 V1 并启动监控（FR-T-005 / FR-T-006）。

    发布前完成必填校验：方向、期限、负责人、预期和复核日（PRD 7.1 第 4 步）。
    缺预期的假设会被拒绝——没有预期就无法算预期差，卡片发布后监控是空转。
    """
    record = uow.thesis.get(thesis_id)
    if record is None:
        raise ValidationFailed(f"逻辑 {thesis_id} 不存在")
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis_id,
        owner=record.owner,
        visibility=record.visibility,
        team=record.team,
    )
    if record.owner != actor.user_id:
        raise HumanGateRequired("只有负责人可以发布逻辑")
    if record.status is not ThesisStatus.DRAFT:
        raise ValidationFailed(f"只有草稿可以发布，当前状态 {record.status.value}")

    hypotheses = uow.thesis.list_hypotheses(thesis_id)
    if not any(h.importance is Importance.CORE for h in hypotheses):
        raise ValidationFailed("至少需要一条核心假设（PRD 5.1）")

    missing = [
        h.hypothesis_id
        for h in hypotheses
        if h.importance is Importance.CORE and not uow.thesis.list_mappings(h.hypothesis_id)
    ]
    if missing:
        raise ValidationFailed(f"核心假设缺少验证指标与预期: {'、'.join(missing)}")

    published = replace(
        record,
        status=ThesisStatus.VALIDATING,
        direction=direction,
        horizon_end_on=horizon_end_on,
        next_review_at=next_review_at,
        invalidation_require_all=invalidation_require_all,
        version=1,
    )
    uow.thesis.update(published)

    version.create(
        uow.versions,
        thesis=published,
        hypotheses=hypotheses,
        triggered_by=version.TRIGGER_PUBLISH,
        created_by=actor.user_id,
        change_reason="发布 V1",
    )
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.PUBLISH,
        object_type="thesis",
        object_id=thesis_id,
        detail={"direction": direction, "next_review_at": next_review_at.isoformat()},
    )
    return published


def recall_candidates(
    uow: UnitOfWork,
    *,
    security_id: str,
    actor: Actor,
) -> list[tuple[ThesisRecord, list[HypothesisRecord]]]:
    """按证券召回候选逻辑与假设（FR-R-002）。

    只返回可见的逻辑：越权召回会通过「你的资料匹配到某条逻辑」间接泄露他人研究
    方向。草稿不参与召回，未发布的逻辑不应该被新资料触发。
    """
    results: list[tuple[ThesisRecord, list[HypothesisRecord]]] = []
    for record in uow.thesis.find_by_security(security_id):
        if record.status in (ThesisStatus.DRAFT, ThesisStatus.CLOSED):
            continue
        if not permission.can_view_thesis(
            actor, owner=record.owner, visibility=record.visibility, team=record.team
        ):
            continue
        results.append((record, uow.thesis.list_hypotheses(record.thesis_id)))
    return results
