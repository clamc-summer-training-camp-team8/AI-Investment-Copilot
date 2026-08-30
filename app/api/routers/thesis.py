"""逻辑卡片路由。

这一层很薄：解析请求、取身份、调一个 service、组装响应。出现业务分支判断说明
代码放错了模块，应当移到 app/services。

错误码映射（contracts/api/README.md）：
解析失败 422 / 实体歧义 409 / 模型失败 503 / 校验失败 400 / 未认证 401 /
**无权限 404**（不是 403：403 会暴露对象存在性，可用于枚举他人研究覆盖）。
"""

from __future__ import annotations

from typing import Annotated, TypeVar
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from app.ai.gateway import Gateway, ModelUnavailable
from app.api.deps import ActorDep, SettingsDep, UowDep
from app.api.feed_presenter import to_feed_item
from app.core.domain import (
    EvidenceRecord,
    MetricMappingRecord,
    ThesisQuery,
    ThesisRecord,
    UnitOfWork,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
)
from app.schemas.thesis import (
    AuditOut,
    AuditPage,
    EvidenceActionIn,
    EvidenceDetailOut,
    EvidenceFeedPage,
    EvidenceOut,
    EvidenceRelationDeactivateIn,
    EvidenceRelationIn,
    EvidenceRelationMutationOut,
    EvidenceRelationOut,
    EvidenceRelationReviewIn,
    EvidenceRetrievalTraceOut,
    HypothesisOut,
    HypothesisTrendOut,
    HypothesisUpdateIn,
    MetricMappingIn,
    MetricMappingOut,
    PageMeta,
    PublishReadinessItemOut,
    PublishReadinessOut,
    StatusDecisionIn,
    SuggestionOut,
    ThesisDraftIn,
    ThesisOut,
    ThesisPage,
    ThesisPublishIn,
    TrendPointOut,
)
from app.services import assets as asset_service
from app.services import audit, permission
from app.services import evidence as evidence_service
from app.services import query as query_service
from app.services import relation as relation_service
from app.services import security as security_service
from app.services import status as status_service
from app.services import thesis as thesis_service
from app.services.errors import (
    EntityAmbiguous,
    HumanGateRequired,
    IllegalTransition,
    NotVisible,
    ThesisAlreadyExists,
    ValidationFailed,
)
from app.services.permission import Actor

E = TypeVar("E", ThesisStatus, ImpactDirection, ConfirmationStatus)

router = APIRouter(tags=["thesis"])


def _require_visible(uow: UnitOfWork, actor: Actor, thesis_id: str) -> ThesisRecord:
    """取卡片并校验可见性。

    不存在与无权限都返回 404：403 会确认对象存在，配合 ID 枚举可以还原他人的
    研究覆盖范围。所有读写卡片的路由都要先过这里。
    """
    record = uow.thesis.get(thesis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="逻辑不存在或无访问权限")
    try:
        permission.ensure_thesis_visible(
            actor,
            thesis_id=thesis_id,
            owner=record.owner,
            visibility=record.visibility,
            team=record.team,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record


def _to_out(uow: UnitOfWork, thesis_id: str) -> ThesisOut:
    record = uow.thesis.get(thesis_id)
    if record is None:
        raise HTTPException(status_code=404, detail="逻辑不存在或无访问权限")
    hypotheses = uow.thesis.list_hypotheses(thesis_id)
    suggestions = record.draft_suggestions or {}
    hypothesis_suggestions = suggestions.get("hypotheses", {})
    if not isinstance(hypothesis_suggestions, dict):
        hypothesis_suggestions = {}
    return ThesisOut(
        thesis_id=record.thesis_id,
        security_id=record.security_id,
        title=record.title,
        direction=record.direction,
        core_view=record.core_view,
        status=record.status.value,
        owner=record.owner,
        visibility=record.visibility,
        version=record.version,
        established_on=record.established_on,
        horizon_end_on=record.horizon_end_on,
        next_review_at=record.next_review_at,
        hypotheses=[
            HypothesisOut(
                hypothesis_id=h.hypothesis_id,
                statement=h.statement,
                hypothesis_type=h.hypothesis_type,
                importance=h.importance.value,
                status=h.status,
                observation_window=h.observation_window,
                invalidation_rule=h.invalidation_rule,
                metric_suggestions=(
                    hypothesis_suggestions.get(h.hypothesis_id, {}).get("metric_suggestions", [])
                    if isinstance(hypothesis_suggestions.get(h.hypothesis_id), dict)
                    else []
                ),
                mappings=[_mapping_out(item) for item in uow.thesis.list_mappings(h.hypothesis_id)],
            )
            for h in hypotheses
        ],
        risk_suggestions=(
            suggestions.get("risks", []) if isinstance(suggestions.get("risks"), list) else []
        ),
        invalidation_suggestions=(
            suggestions.get("invalidation_suggestions", [])
            if isinstance(suggestions.get("invalidation_suggestions"), list)
            else []
        ),
    )


def _mapping_out(record: MetricMappingRecord) -> MetricMappingOut:
    return MetricMappingOut(
        mapping_id=record.mapping_id,
        metric_id=record.metric_id,
        metric_version=record.metric_version,
        expected_direction=record.expected_direction.value,
        expected_value=record.expected_value,
        invalidation_threshold=record.invalidation_threshold,
        invalidation_consecutive_periods=record.invalidation_consecutive_periods,
        expectation_source=record.expectation_source or "",
        confirmation_status=record.confirmation_status.value,
    )


@router.post(
    "/theses/drafts",
    response_model=ThesisOut,
    status_code=201,
    responses={409: {"description": "该公司已经维护一条投资逻辑"}},
)
def create_draft(
    payload: ThesisDraftIn,
    actor: ActorDep,
    uow: UowDep,
    conf: SettingsDep,
) -> ThesisOut:
    """从观点生成卡片草稿（FR-T-001 / FR-T-002）。草稿不会自动发布。"""
    try:
        security = security_service.require(uow, payload.security_id)
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 唯一逻辑检查必须早于 RAG 和模型调用，避免明知不能建卡仍消耗检索/模型资源。
    existing = uow.thesis.get_by_security(security.security_id)
    if existing is not None:
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
        detail: dict[str, object] = {
            "code": "THESIS_ALREADY_EXISTS",
            "message": "该公司已维护一条投资逻辑，请打开现有逻辑进行修订",
        }
        if visible_id is not None:
            detail["thesis_id"] = visible_id
        raise HTTPException(status_code=409, detail=detail)
    try:
        gateway = Gateway.build(conf)
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    segments: list[tuple[str, str]] = []
    source_document_id = payload.document_id
    if payload.use_rag:
        try:
            hits = asset_service.hybrid_retrieve(
                uow,
                query=payload.view,
                actor=actor,
                settings=conf,
                security_ids=(security.security_id,),
                limit=8,
            )
        except ValidationFailed as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        segments = [(hit.locator, hit.content) for hit in hits]
        if hits:
            source_document_id = hits[0].document_id

    try:
        outcome = gateway.thesis_draft(
            security_id=security.security_id,
            view=payload.view,
            segments=segments,
            source_document_id=source_document_id,
        )
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not outcome.usable:
        raise HTTPException(
            status_code=422,
            detail={"code": "AI_OUTPUT_INVALID", "errors": outcome.errors[:5]},
        )

    audit.record_model_call(
        uow.audit,
        actor=actor.user_id,
        object_type="thesis_draft",
        object_id=security.security_id,
        model_version=str(outcome.payload.get("model_version", "")),
        prompt_version=str(outcome.payload.get("prompt_version", "")),
        ai_status=outcome.ai_status.value,
        model_metadata=(
            outcome.payload.get("model_metadata")
            if isinstance(outcome.payload.get("model_metadata"), dict)
            else None
        ),
    )

    # 用 uuid4 而不是 hash(view)：CPython 的字符串 hash 按进程随机化，同一观点
    # 换个进程就变 ID；同进程内重复建卡又会撞主键，flush 抛 IntegrityError 变 500。
    thesis_id = f"THS-{security.security_id[:24]}-{uuid4().hex[:12]}"
    try:
        thesis_service.create_draft(uow, thesis_id=thesis_id, draft=outcome.payload, actor=actor)
    except EntityAmbiguous as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "ENTITY_AMBIGUOUS", "candidates": exc.candidates},
        ) from exc
    except ThesisAlreadyExists as exc:
        detail = {"code": "THESIS_ALREADY_EXISTS", "message": str(exc)}
        if exc.thesis_id is not None:
            detail["thesis_id"] = exc.thesis_id
        raise HTTPException(status_code=409, detail=detail) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_out(uow, thesis_id)


@router.get("/theses", response_model=ThesisPage)
def list_theses(
    actor: ActorDep,
    uow: UowDep,
    status: Annotated[list[str] | None, Query(description="按状态过滤，可多值")] = None,
    security_id: Annotated[list[str] | None, Query(description="按标的过滤，可多值")] = None,
    owner: Annotated[str | None, Query(description="按负责人过滤")] = None,
    keyword: Annotated[
        str | None, Query(max_length=100, description="标题与核心观点模糊匹配")
    ] = None,
    manageable: Annotated[bool, Query(description="仅返回当前用户可管理的逻辑")] = False,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ThesisPage:
    """卡片列表。强制分页，只返回当前用户可见的卡片。

    `page.total` 是过滤后的候选总数，当页条数可能少于 limit——可见性过滤在取回
    当页之后进行，理由见 app/services/query.py 的 list_theses。
    """
    statuses = tuple(_parse_required_enum(ThesisStatus, s, "状态") for s in (status or []))
    page = query_service.list_theses(
        uow,
        actor,
        ThesisQuery(
            statuses=statuses,
            securities=tuple(security_id or []),
            # 关联目标选择只交给负责人。由服务端将可管理条件转为负责人过滤，
            # 页面无需、也不得下载可见但不可修改的逻辑后再自行筛选。
            owner=actor.user_id if manageable else owner,
            keyword=keyword,
            limit=limit,
            offset=offset,
        ),
    )
    return ThesisPage(
        items=[_to_out(uow, r.thesis_id) for r in page.items],
        page=PageMeta(total=page.total, limit=page.limit, offset=page.offset),
    )


@router.get("/theses/{thesis_id}", response_model=ThesisOut)
def get_thesis(thesis_id: str, actor: ActorDep, uow: UowDep) -> ThesisOut:
    _require_visible(uow, actor, thesis_id)

    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.VIEW,
        object_type="thesis",
        object_id=thesis_id,
    )
    return _to_out(uow, thesis_id)


@router.post("/theses/{thesis_id}/publish", response_model=ThesisOut)
def publish(
    thesis_id: str,
    payload: ThesisPublishIn,
    actor: ActorDep,
    uow: UowDep,
) -> ThesisOut:
    """发布，生成 V1（FR-T-005）。只有负责人可以发布。"""
    _require_visible(uow, actor, thesis_id)
    try:
        thesis_service.publish(
            uow,
            thesis_id=thesis_id,
            actor=actor,
            direction=payload.direction,
            horizon_end_on=payload.horizon_end_on,
            next_review_at=payload.next_review_at,
            invalidation_require_all=payload.invalidation_require_all,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(uow, thesis_id)


@router.post("/theses/{thesis_id}/publish-readiness", response_model=PublishReadinessOut)
def publish_readiness(
    thesis_id: str,
    payload: ThesisPublishIn,
    actor: ActorDep,
    uow: UowDep,
) -> PublishReadinessOut:
    _require_visible(uow, actor, thesis_id)
    try:
        checks = thesis_service.publish_readiness(
            uow,
            thesis_id=thesis_id,
            actor=actor,
            direction=payload.direction,
            horizon_end_on=payload.horizon_end_on,
            next_review_at=payload.next_review_at,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = [
        PublishReadinessItemOut(code=code, label=label, passed=passed, message=message)
        for code, label, passed, message in checks
    ]
    return PublishReadinessOut(ready=all(item.passed for item in items), items=items)


@router.patch("/theses/{thesis_id}/hypotheses/{hypothesis_id}", response_model=ThesisOut)
def update_hypothesis(
    thesis_id: str,
    hypothesis_id: str,
    payload: HypothesisUpdateIn,
    actor: ActorDep,
    uow: UowDep,
) -> ThesisOut:
    _require_visible(uow, actor, thesis_id)
    try:
        thesis_service.update_hypothesis(
            uow,
            thesis_id=thesis_id,
            hypothesis_id=hypothesis_id,
            statement=payload.statement,
            hypothesis_type=payload.hypothesis_type,
            importance=Importance(payload.importance),
            observation_window=payload.observation_window,
            invalidation_rule=payload.invalidation_rule,
            actor=actor,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_out(uow, thesis_id)


@router.post(
    "/theses/{thesis_id}/hypotheses/{hypothesis_id}/mappings",
    response_model=MetricMappingOut,
)
def set_hypothesis_mapping(
    thesis_id: str,
    hypothesis_id: str,
    payload: MetricMappingIn,
    actor: ActorDep,
    uow: UowDep,
) -> MetricMappingOut:
    _require_visible(uow, actor, thesis_id)
    if payload.mapping_id and not any(
        item.mapping_id == payload.mapping_id for item in uow.thesis.list_mappings(hypothesis_id)
    ):
        raise HTTPException(status_code=400, detail="映射不存在或不属于当前假设")
    mapping_id = payload.mapping_id or f"MAP-{uuid4().hex[:20]}"
    try:
        record = thesis_service.set_expectations(
            uow,
            hypothesis_id=hypothesis_id,
            mapping=MetricMappingRecord(
                mapping_id=mapping_id,
                hypothesis_id=hypothesis_id,
                metric_id=payload.metric_id,
                metric_version=payload.metric_version,
                expected_direction=ExpectationDirection(payload.expected_direction),
                expected_value=payload.expected_value,
                invalidation_threshold=payload.invalidation_threshold,
                invalidation_consecutive_periods=payload.invalidation_consecutive_periods,
                expectation_source=payload.expectation_source,
                confirmation_status=ConfirmationStatus.CONFIRMED,
            ),
            actor=actor,
            validate_metric=True,
            thesis_id=thesis_id,
            require_draft=True,
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _mapping_out(record)


@router.get("/theses/{thesis_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(thesis_id: str, actor: ActorDep, uow: UowDep) -> list[EvidenceOut]:
    _require_visible(uow, actor, thesis_id)
    return [
        EvidenceOut(
            evidence_id=e.evidence_id,
            thesis_id=e.thesis_id,
            hypothesis_id=e.hypothesis_id,
            evidence_type=e.evidence_type,
            direction=e.direction.value,
            evidence_locator=e.evidence_locator,
            confirmation_status=e.confirmation_status.value,
            ai_status=e.ai_status,
            model_version=e.model_version,
            prompt_version=e.prompt_version,
            strength=e.strength,
            strength_score=e.strength_score,
            ai_confidence=e.ai_confidence,
            confirmed_by=e.confirmed_by,
            confirmed_at=e.confirmed_at,
        )
        for e in uow.evidence.list_for_thesis(thesis_id)
    ]


@router.get("/theses/{thesis_id}/evidence-feed", response_model=EvidenceFeedPage)
def list_readable_evidence(
    thesis_id: str,
    actor: ActorDep,
    uow: UowDep,
    status: Annotated[list[str] | None, Query()] = None,
    direction: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidenceFeedPage:
    """返回逻辑下可直接阅读的证据摘要，不改变旧证据列表契约。"""
    _require_visible(uow, actor, thesis_id)
    statuses = tuple(
        _parse_required_enum(ConfirmationStatus, item, "确认状态") for item in (status or [])
    )
    parsed_direction = (
        _parse_required_enum(ImpactDirection, direction, "影响方向") if direction else None
    )
    records, total = uow.feed.search(
        thesis_ids=(thesis_id,),
        statuses=statuses,
        direction=parsed_direction,
        limit=limit,
        offset=offset,
    )
    return EvidenceFeedPage(
        items=[to_feed_item(item, actor_id=actor.user_id) for item in records],
        page=PageMeta(total=total, limit=limit, offset=offset),
    )


@router.get("/evidence/{evidence_id}", response_model=EvidenceDetailOut)
def get_evidence_detail(evidence_id: str, actor: ActorDep, uow: UowDep) -> EvidenceDetailOut:
    """读取可核验的证据本体详情，不以单一逻辑关系作为详情字段。"""
    record = _require_visible_evidence(evidence_id, actor=actor, uow=uow)
    required = (
        record.security_id,
        record.fact_excerpt,
        record.source_document_id,
        record.source_document_title,
        record.disclosed_at,
        record.source_url,
    )
    if any(value is None for value in required):
        raise HTTPException(status_code=422, detail="证据详情字段不完整，无法用于公开核验")
    return EvidenceDetailOut(
        evidence_id=record.evidence_id,
        evidence_type=record.evidence_type,
        direction=record.direction.value,
        evidence_locator=record.evidence_locator,
        confirmation_status=record.confirmation_status.value,
        ai_status=record.ai_status,
        model_version=record.model_version,
        prompt_version=record.prompt_version,
        strength=record.strength,
        strength_score=record.strength_score,
        ai_confidence=record.ai_confidence,
        confirmed_by=record.confirmed_by,
        confirmed_at=record.confirmed_at,
        security_id=record.security_id,
        fact_excerpt=record.fact_excerpt,
        source_document_id=record.source_document_id,
        source_document_title=record.source_document_title,
        disclosed_at=record.disclosed_at,
        occurred_at=record.occurred_at,
        source_url=record.source_url,
    )


def _require_visible_evidence(evidence_id: str, *, actor: Actor, uow: UnitOfWork) -> EvidenceRecord:
    record = uow.evidence.get(evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="证据不存在或无访问权限")
    # 证据正文由可见的有效关联授权访问。原 Evidence.thesis_id 仅为旧模型兼容字段，
    # 不应阻断后来新增到当前用户可见逻辑中的同一条证据。
    relations = uow.relations.list_for_evidence(evidence_id)
    if relations:
        visible_relation = False
        for relation in relations:
            if relation.status.value == "已解除":
                continue
            try:
                _require_visible(uow, actor, relation.thesis_id)
                visible_relation = True
                break
            except HTTPException:
                continue
        if not visible_relation:
            raise HTTPException(status_code=404, detail="证据不存在或无访问权限")
    else:
        _require_visible(uow, actor, record.thesis_id)
    if not permission.can_read_document(actor, visibility_label=record.source_visibility_label):
        raise HTTPException(status_code=404, detail="证据不存在或无访问权限")
    return record


@router.get(
    "/evidence/{evidence_id}/retrieval-trace",
    response_model=EvidenceRetrievalTraceOut,
)
def get_evidence_retrieval_trace(
    evidence_id: str, actor: ActorDep, uow: UowDep
) -> EvidenceRetrievalTraceOut:
    """读取候选证据生成时冻结的文本/图双路召回依据。"""

    record = _require_visible_evidence(evidence_id, actor=actor, uow=uow)
    trace = record.retrieval_trace
    if not trace:
        return EvidenceRetrievalTraceOut(
            available=False,
            retrieval_mode="unavailable",
            retrieval_version="unknown",
            locator=record.evidence_locator,
            final_score=0.0,
            score_components={"text": 0.0, "graph": 0.0},
            graph_paths=[],
            graph_snapshot=None,
        )
    return EvidenceRetrievalTraceOut.model_validate(trace)


@router.get("/evidence/{evidence_id}/relations", response_model=list[EvidenceRelationOut])
def list_evidence_relations(
    evidence_id: str, actor: ActorDep, uow: UowDep
) -> list[EvidenceRelationOut]:
    """兼容输出当前单关联记录；多关联迁移后保持同一路径与响应形状。"""
    record = uow.evidence.get(evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="证据不存在或无访问权限")
    relations = uow.relations.list_for_evidence(evidence_id)
    # 已完成迁移的数据库从关联表读取；空库/旧库保留一条兼容输出，便于增量升级。
    if not relations:
        thesis = _require_visible(uow, actor, record.thesis_id)
        return [
            _relation_out(
                relation_id=f"legacy-{record.evidence_id}",
                thesis_id=record.thesis_id,
                hypothesis_id=record.hypothesis_id,
                direction=record.direction.value,
                strength=record.strength,
                status=record.confirmation_status.value,
                reason=record.review_note,
                created_by=record.confirmed_by or "系统迁移",
                can_manage=thesis.owner == actor.user_id,
            )
        ]
    result: list[EvidenceRelationOut] = []
    for relation in relations:
        target_thesis = uow.thesis.get(relation.thesis_id)
        if target_thesis is None:
            continue
        try:
            permission.ensure_thesis_visible(
                actor,
                thesis_id=target_thesis.thesis_id,
                owner=target_thesis.owner,
                visibility=target_thesis.visibility,
                team=target_thesis.team,
            )
        except NotVisible:
            continue
        result.append(
            _relation_out(
                relation_id=relation.relation_id,
                thesis_id=relation.thesis_id,
                hypothesis_id=relation.hypothesis_id,
                direction=relation.direction.value,
                strength=relation.strength,
                status=relation.status.value,
                reason=relation.reason,
                created_by=relation.created_by,
                reviewed_by=relation.reviewed_by,
                reviewed_at=relation.reviewed_at,
                deactivated_by=relation.deactivated_by,
                deactivated_at=relation.deactivated_at,
                can_manage=target_thesis.owner == actor.user_id,
            )
        )
    return result


def _relation_out(
    *,
    relation_id: str,
    thesis_id: str,
    hypothesis_id: str,
    direction: str,
    strength: str | None,
    status: str,
    reason: str | None,
    created_by: str,
    reviewed_by=None,
    reviewed_at=None,
    deactivated_by=None,
    deactivated_at=None,
    can_manage: bool,
) -> EvidenceRelationOut:
    return EvidenceRelationOut(
        relation_id=relation_id,
        thesis_id=thesis_id,
        hypothesis_id=hypothesis_id,
        direction=direction,
        strength=strength,
        status=status,
        reason=reason,
        created_by=created_by,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        deactivated_by=deactivated_by,
        deactivated_at=deactivated_at,
        can_manage=can_manage,
    )


def _relation_mutation(record, actor: Actor, uow: UnitOfWork) -> EvidenceRelationMutationOut:
    thesis = uow.thesis.get(record.thesis_id)
    return EvidenceRelationMutationOut(
        relation=_relation_out(
            relation_id=record.relation_id,
            thesis_id=record.thesis_id,
            hypothesis_id=record.hypothesis_id,
            direction=record.direction.value,
            strength=record.strength,
            status=record.status.value,
            reason=record.reason,
            created_by=record.created_by,
            reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at,
            deactivated_by=record.deactivated_by,
            deactivated_at=record.deactivated_at,
            can_manage=bool(thesis and thesis.owner == actor.user_id),
        ),
        affected_thesis_ids=[record.thesis_id],
    )


@router.post(
    "/evidence/{evidence_id}/relations", response_model=EvidenceRelationMutationOut, status_code=201
)
def create_relation(
    evidence_id: str, payload: EvidenceRelationIn, actor: ActorDep, uow: UowDep
) -> EvidenceRelationMutationOut:
    evidence = uow.evidence.get(evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="证据不存在或无访问权限")
    _require_visible(uow, actor, evidence.thesis_id)
    try:
        relation = relation_service.create(
            uow,
            evidence_id=evidence_id,
            thesis_id=payload.thesis_id,
            hypothesis_id=payload.hypothesis_id,
            direction=_parse_required_enum(ImpactDirection, payload.direction, "影响方向"),
            strength=payload.strength,
            reason=payload.reason,
            actor=actor,
        )
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _relation_mutation(relation, actor, uow)


@router.patch(
    "/evidence/{evidence_id}/relations/{relation_id}", response_model=EvidenceRelationMutationOut
)
def update_relation(
    evidence_id: str, relation_id: str, payload: EvidenceRelationIn, actor: ActorDep, uow: UowDep
) -> EvidenceRelationMutationOut:
    relation = uow.relations.get(relation_id)
    if relation is None or relation.evidence_id != evidence_id:
        raise HTTPException(status_code=404, detail="证据关联不存在或无访问权限")
    _require_visible(uow, actor, relation.thesis_id)
    try:
        updated = relation_service.update(
            uow,
            relation_id=relation_id,
            hypothesis_id=payload.hypothesis_id,
            direction=_parse_required_enum(ImpactDirection, payload.direction, "影响方向"),
            strength=payload.strength,
            reason=payload.reason,
            actor=actor,
        )
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _relation_mutation(updated, actor, uow)


@router.post(
    "/evidence/{evidence_id}/relations/{relation_id}/deactivate",
    response_model=EvidenceRelationMutationOut,
)
def deactivate_relation(
    evidence_id: str,
    relation_id: str,
    payload: EvidenceRelationDeactivateIn,
    actor: ActorDep,
    uow: UowDep,
) -> EvidenceRelationMutationOut:
    relation = uow.relations.get(relation_id)
    if relation is None or relation.evidence_id != evidence_id:
        raise HTTPException(status_code=404, detail="证据关联不存在或无访问权限")
    _require_visible(uow, actor, relation.thesis_id)
    try:
        updated = relation_service.deactivate(
            uow, relation_id=relation_id, reason=payload.reason, actor=actor
        )
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _relation_mutation(updated, actor, uow)


@router.post(
    "/evidence/{evidence_id}/relations/{relation_id}/review",
    response_model=EvidenceRelationMutationOut,
)
def review_relation(
    evidence_id: str,
    relation_id: str,
    payload: EvidenceRelationReviewIn,
    actor: ActorDep,
    uow: UowDep,
    conf: SettingsDep,
) -> EvidenceRelationMutationOut:
    relation = uow.relations.get(relation_id)
    if relation is None or relation.evidence_id != evidence_id:
        raise HTTPException(status_code=404, detail="证据关联不存在或无访问权限")
    _require_visible(uow, actor, relation.thesis_id)
    try:
        updated, _ = relation_service.review(
            uow,
            relation_id=relation_id,
            action=payload.action,
            reason=payload.reason,
            actor=actor,
            thresholds=conf.rules,
        )
    except HumanGateRequired as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _relation_mutation(updated, actor, uow)


@router.post("/evidence/{evidence_id}/actions", response_model=list[SuggestionOut])
def act_on_evidence(
    evidence_id: str,
    payload: EvidenceActionIn,
    actor: ActorDep,
    uow: UowDep,
    conf: SettingsDep,
) -> list[SuggestionOut]:
    """处置候选证据（FR-R-004）。确认后重算建议，但**不改状态**。"""
    record = uow.evidence.get(evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="证据不存在或无访问权限")
    thesis_record = _require_visible(uow, actor, record.thesis_id)

    # 迁移后的正式状态计算只读 EvidenceRelation。历史 actions 接口在恰有一条
    # 有效关联时委托关联审核；多关联时拒绝，避免用户误以为处置了全部关系。
    active_relations = [
        relation
        for relation in uow.relations.list_for_evidence(evidence_id)
        if relation.status.value != "已解除"
    ]
    if active_relations and payload.action in {"确认", "驳回", "暂不判断"}:
        if len(active_relations) != 1:
            raise HTTPException(status_code=409, detail="EVIDENCE_MULTIPLE_RELATIONS")
        try:
            relation_service.review(
                uow,
                relation_id=active_relations[0].relation_id,
                action=payload.action,
                reason=payload.note,
                actor=actor,
                thresholds=conf.rules,
            )
        except HumanGateRequired as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValidationFailed as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _suggestions(uow, active_relations[0].thesis_id)

    try:
        evidence_service.handle(
            uow,
            evidence_id=evidence_id,
            action=payload.action,
            actor=actor,
            thesis=thesis_record,
            hypotheses=uow.thesis.list_hypotheses(thesis_record.thesis_id),
            thresholds=conf.rules,
            note=payload.note,
            new_hypothesis_id=payload.new_hypothesis_id,
            new_direction=_parse_enum(ImpactDirection, payload.new_direction, "影响方向"),
        )
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _suggestions(uow, thesis_record.thesis_id)


@router.get("/theses/{thesis_id}/suggestions", response_model=list[SuggestionOut])
def list_suggestions(thesis_id: str, actor: ActorDep, uow: UowDep) -> list[SuggestionOut]:
    """状态建议列表。

    必须过权限：建议里含假设编号、突破情况与研究员判断，等于他人研究结论的摘要。
    """
    _require_visible(uow, actor, thesis_id)
    return _suggestions(uow, thesis_id)


@router.post("/theses/{thesis_id}/status", response_model=ThesisOut)
def decide_status(
    thesis_id: str,
    payload: StatusDecisionIn,
    actor: ActorDep,
    uow: UowDep,
) -> ThesisOut:
    """人工处置状态建议。这是唯一能改状态的接口（FR-S-003）。

    先过可见性，再校验只有负责人能改状态：填了原因不等于有权改别人的卡片。
    """
    record = _require_visible(uow, actor, thesis_id)
    if record.owner != actor.user_id:
        raise HTTPException(status_code=403, detail="只有负责人可以变更逻辑状态")

    try:
        status_service.apply_decision(
            uow,
            thesis=record,
            hypotheses=uow.thesis.list_hypotheses(thesis_id),
            suggestion_id=payload.suggestion_id,
            action=payload.action,
            actor=actor.user_id,
            reason=payload.reason,
            target_status=_parse_enum(ThesisStatus, payload.target_status, "目标状态"),
        )
    except HumanGateRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_out(uow, thesis_id)


@router.get("/theses/{thesis_id}/trends", response_model=list[HypothesisTrendOut])
def list_trends(
    thesis_id: str,
    actor: ActorDep,
    uow: UowDep,
    settings: SettingsDep,
) -> list[HypothesisTrendOut]:
    """按假设返回趋势（FR-V-002：最近 4-8 期）。

    没有指标映射的假设也返回一行、`direction` 为「无量化指标」，前端据此显示
    「需人工判断」。静默跳过会让界面上少一条假设。
    """
    thesis_record = _require_visible(uow, actor, thesis_id)
    trends = query_service.hypothesis_trends(uow, thesis_record, thresholds=settings.rules)

    out: list[HypothesisTrendOut] = []
    for item in trends:
        result = item.result
        out.append(
            HypothesisTrendOut(
                hypothesis_id=item.hypothesis_id,
                statement=item.statement,
                metric_id=item.metric_id,
                unit=item.unit,
                period_type=item.period_type,
                metric_version=item.metric_version,
                data_version=item.data_version,
                direction=result.direction if result else "无量化指标",
                slope=result.slope if result else None,
                consecutive_decline=result.consecutive_decline if result else 0,
                consecutive_below_expectation=(
                    result.consecutive_below_expectation if result else 0
                ),
                verdict=result.verdict.value if result else None,
                points=(
                    [
                        TrendPointOut(period=period, value=value)
                        for period, value in zip(result.periods, result.values, strict=True)
                    ]
                    if result
                    else []
                ),
                note=item.note,
            )
        )
    return out


@router.get("/theses/{thesis_id}/audit", response_model=AuditPage)
def list_audit(
    thesis_id: str,
    actor: ActorDep,
    uow: UowDep,
    limit: Annotated[int, Query(ge=1, le=query_service.MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    """卡片留痕（PRD 12.2：高影响输出可追溯）。倒序，最近的在前。"""
    _require_visible(uow, actor, thesis_id)
    records, total = query_service.audit_trail(
        uow, object_type="thesis", object_id=thesis_id, limit=limit, offset=offset
    )
    return AuditPage(
        items=[
            AuditOut(
                actor=r.actor,
                action=r.action,
                object_type=r.object_type,
                object_id=r.object_id,
                model_version=r.model_version,
                occurred_at=r.occurred_at,
                detail=r.detail,
            )
            for r in records
        ],
        page=PageMeta(total=total, limit=limit, offset=offset),
    )


def _parse_required_enum(enum_cls: type[E], raw: str, label: str) -> E:
    """查询参数版的枚举解析：值必填，非法即 400。"""
    parsed = _parse_enum(enum_cls, raw, label)
    if parsed is None:
        raise HTTPException(status_code=400, detail=f"{label} 不能为空")
    return parsed


def _parse_enum(enum_cls: type[E], raw: str | None, label: str) -> E | None:
    """把字符串转枚举。非法取值是校验失败（400），不是服务端错误（500）。"""
    if not raw:
        return None
    try:
        return enum_cls(raw)
    except ValueError as exc:
        allowed = "、".join(str(m.value) for m in enum_cls)
        raise HTTPException(
            status_code=400, detail=f"{label} {raw!r} 非法，可选：{allowed}"
        ) from exc


def _suggestions(uow: UnitOfWork, thesis_id: str) -> list[SuggestionOut]:
    return [
        SuggestionOut(
            suggestion_id=s.suggestion_id,
            thesis_id=s.thesis_id,
            current_status=s.current_status.value,
            suggested_status=s.suggested_status.value,
            reasons=s.reasons,
            triggered_hypotheses=s.triggered_hypotheses,
            rule_version=s.rule_version,
            human_action=s.human_action,
            human_reason=s.human_reason,
            acted_by=s.acted_by,
        )
        for s in uow.suggestions.list_for_thesis(thesis_id)
    ]
