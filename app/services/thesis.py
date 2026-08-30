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
from app.services.errors import (
    EntityAmbiguous,
    HumanGateRequired,
    NotVisible,
    ThesisAlreadyExists,
    ValidationFailed,
)
from app.services.permission import Actor
from app.services.ports import (
    HypothesisRecord,
    MetricMappingRecord,
    ThesisRecord,
    UnitOfWork,
)

TITLE_MAX = 40
CORE_VIEW_MAX = 200


def _ensure_current(record: ThesisRecord) -> None:
    if not record.is_current:
        suffix = (
            f"，请维护 {record.superseded_by_thesis_id}" if record.superseded_by_thesis_id else ""
        )
        raise ValidationFailed(f"历史投资逻辑只读{suffix}")


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

    existing = uow.thesis.get_by_security(str(security_id))
    if existing is not None:
        # 数据库唯一约束是并发写入的最后防线；这里在模型结果落库前给出可理解的
        # 业务冲突。历史异常数据若已存在多条，也绝不再制造第三条。
        visible_id: str | None = None
        try:
            permission.ensure_thesis_visible(
                actor,
                thesis_id=existing.thesis_id,
                owner=existing.owner,
                visibility=existing.visibility,
                team=existing.team,
            )
        except NotVisible:
            pass
        else:
            visible_id = existing.thesis_id
        raise ThesisAlreadyExists(
            "该公司已维护一条投资逻辑，请在现有逻辑中通过修订更新",
            visible_id,
        )

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
        draft_suggestions={
            "hypotheses": {
                f"{thesis_id}-H{index}": {
                    "metric_suggestions": item.get("metric_suggestions") or [],
                }
                for index, item in enumerate(hypotheses, start=1)
            },
            "risks": draft.get("risks") or [],
            "invalidation_suggestions": draft.get("invalidation_suggestions") or [],
        },
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


def update_hypothesis(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    hypothesis_id: str,
    statement: str,
    hypothesis_type: str,
    importance: Importance,
    observation_window: str | None,
    invalidation_rule: str | None,
    actor: Actor,
) -> HypothesisRecord:
    """人工编辑草稿假设；AI 建议不会自动采用。"""
    thesis = _require_owned_draft(uow, thesis_id=thesis_id, actor=actor)
    hypothesis = uow.thesis.get_hypothesis(hypothesis_id)
    if hypothesis is None or hypothesis.thesis_id != thesis.thesis_id:
        raise ValidationFailed(f"假设 {hypothesis_id} 不属于逻辑 {thesis_id}")
    normalized_statement = statement.strip()
    if not normalized_statement:
        raise ValidationFailed("假设内容不能为空")
    updated = replace(
        hypothesis,
        statement=normalized_statement,
        hypothesis_type=hypothesis_type.strip() or "其他",
        importance=importance,
        observation_window=(observation_window or "").strip() or None,
        invalidation_rule=(invalidation_rule or "").strip() or None,
    )
    uow.thesis.update_hypothesis(updated)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.EDIT,
        object_type="hypothesis",
        object_id=hypothesis_id,
        detail={
            "statement": updated.statement,
            "hypothesis_type": updated.hypothesis_type,
            "importance": updated.importance.value,
            "observation_window": updated.observation_window,
            "invalidation_rule": updated.invalidation_rule,
        },
    )
    return updated


def set_expectations(
    uow: UnitOfWork,
    *,
    hypothesis_id: str,
    mapping: MetricMappingRecord,
    actor: Actor,
    validate_metric: bool = False,
    thesis_id: str | None = None,
    require_draft: bool = False,
) -> MetricMappingRecord:
    """录入研究员预期与失效阈值。

    这两项只能由人工填写（PRD 10.1 限制、GAP-002 要求记录来源），因此强制要求
    expectation_source 非空——没有来源的预期无法追溯，预期差也就失去意义。
    """
    if mapping.expected_value is None and mapping.invalidation_threshold is None:
        raise ValidationFailed("必须至少给出预期值或失效阈值")
    if not (mapping.expectation_source or "").strip():
        raise ValidationFailed("必须记录预期来源（GAP-002）")
    if mapping.invalidation_consecutive_periods is not None and (
        mapping.invalidation_consecutive_periods < 1
        or mapping.invalidation_consecutive_periods > 12
    ):
        raise ValidationFailed("连续期数必须在 1 至 12 之间")

    hypothesis = uow.thesis.get_hypothesis(hypothesis_id)
    if hypothesis is None:
        raise ValidationFailed(f"假设 {hypothesis_id} 不存在")
    thesis = uow.thesis.get(hypothesis.thesis_id)
    if thesis is None:
        raise ValidationFailed(f"逻辑 {hypothesis.thesis_id} 不存在")
    _ensure_current(thesis)
    if thesis_id is not None and hypothesis.thesis_id != thesis_id:
        raise ValidationFailed(f"假设 {hypothesis_id} 不属于逻辑 {thesis_id}")
    if require_draft and thesis.status is not ThesisStatus.DRAFT:
        raise ValidationFailed("已发布逻辑须通过修订草稿修改")
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis.thesis_id,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    )
    if thesis.owner != actor.user_id:
        raise HumanGateRequired("只有负责人可以配置验证预期")
    if validate_metric and uow.metrics.get(mapping.metric_id, mapping.metric_version) is None:
        raise ValidationFailed(
            f"指标 {mapping.metric_id} {mapping.metric_version} 不存在，请先从指标字典选择"
        )

    saved = replace(
        mapping,
        hypothesis_id=hypothesis_id,
        expectation_source=(mapping.expectation_source or "").strip(),
    )
    existing = next(
        (
            item
            for item in uow.thesis.list_mappings(hypothesis_id)
            if item.mapping_id == saved.mapping_id
        ),
        None,
    )
    if existing is None:
        uow.thesis.add_mapping(saved)
    else:
        uow.thesis.update_mapping(saved)
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
    return saved


def publish_readiness(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    actor: Actor,
    direction: str,
    horizon_end_on: date,
    next_review_at: date,
) -> list[tuple[str, str, bool, str]]:
    """发布约束的单一事实来源，供清单与真正发布共用。"""
    record = uow.thesis.get(thesis_id)
    if record is None:
        raise ValidationFailed(f"逻辑 {thesis_id} 不存在")
    _ensure_current(record)
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis_id,
        owner=record.owner,
        visibility=record.visibility,
        team=record.team,
    )
    hypotheses = uow.thesis.list_hypotheses(thesis_id)
    core = [item for item in hypotheses if item.importance is Importance.CORE]
    missing_mappings = [
        item.hypothesis_id for item in core if not uow.thesis.list_mappings(item.hypothesis_id)
    ]
    today = date.today()
    return [
        (
            "owner",
            "负责人确认",
            record.owner == actor.user_id,
            "当前用户是逻辑负责人" if record.owner == actor.user_id else "只有负责人可以发布",
        ),
        (
            "draft",
            "草稿状态",
            record.status is ThesisStatus.DRAFT,
            "逻辑仍处于可配置草稿" if record.status is ThesisStatus.DRAFT else "只有草稿可以发布",
        ),
        (
            "core_hypothesis",
            "核心假设",
            bool(core),
            f"已选择 {len(core)} 条核心假设" if core else "至少选择一条核心假设",
        ),
        (
            "expectations",
            "验证指标与预期",
            bool(core) and not missing_mappings,
            (
                "全部核心假设已配置指标、预期或阈值"
                if core and not missing_mappings
                else f"待配置：{'、'.join(missing_mappings) or '先选择核心假设'}"
            ),
        ),
        (
            "direction",
            "投资方向",
            direction in {"看多", "看空", "观察"},
            "方向已由研究员确认" if direction in {"看多", "看空", "观察"} else "请选择投资方向",
        ),
        (
            "horizon",
            "监控期限",
            horizon_end_on >= today,
            ("监控期限有效" if horizon_end_on >= today else "监控期限不能早于今天"),
        ),
        (
            "review",
            "复核日期",
            today <= next_review_at <= horizon_end_on,
            (
                "复核日期有效"
                if today <= next_review_at <= horizon_end_on
                else "复核日期须在今天至监控期限之间"
            ),
        ),
    ]


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
    checks = publish_readiness(
        uow,
        thesis_id=thesis_id,
        actor=actor,
        direction=direction,
        horizon_end_on=horizon_end_on,
        next_review_at=next_review_at,
    )
    failed = [message for _, _, passed, message in checks if not passed]
    if failed:
        if record.owner != actor.user_id:
            raise HumanGateRequired(failed[0])
        raise ValidationFailed("；".join(failed))

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

    evidence, data_cutoff_at, model_versions = version.evidence_snapshot(uow, thesis_id)

    version.create(
        uow.versions,
        thesis=published,
        hypotheses=hypotheses,
        triggered_by=version.TRIGGER_PUBLISH,
        created_by=actor.user_id,
        change_reason="发布 V1",
        mappings=[
            mapping
            for hypothesis in hypotheses
            for mapping in uow.thesis.list_mappings(hypothesis.hypothesis_id)
        ],
        evidence=evidence,
        data_cutoff_at=data_cutoff_at,
        rule_version="rules-v1",
        model_versions=model_versions,
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


def _require_owned_draft(uow: UnitOfWork, *, thesis_id: str, actor: Actor) -> ThesisRecord:
    record = uow.thesis.get(thesis_id)
    if record is None:
        raise ValidationFailed(f"逻辑 {thesis_id} 不存在")
    _ensure_current(record)
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis_id,
        owner=record.owner,
        visibility=record.visibility,
        team=record.team,
    )
    if record.owner != actor.user_id:
        raise HumanGateRequired("只有负责人可以编辑逻辑")
    if record.status is not ThesisStatus.DRAFT:
        raise ValidationFailed("已发布逻辑须通过修订草稿修改")
    return record


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
    record = uow.thesis.get_by_security(security_id)
    if record is None or record.status in (ThesisStatus.DRAFT, ThesisStatus.CLOSED):
        return []
    if not permission.can_view_thesis(
        actor, owner=record.owner, visibility=record.visibility, team=record.team
    ):
        return []
    return [(record, uow.thesis.list_hypotheses(record.thesis_id))]
