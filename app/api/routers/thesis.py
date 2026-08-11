"""逻辑卡片路由。

这一层很薄：解析请求、取身份、调一个 service、组装响应。出现业务分支判断说明
代码放错了模块，应当移到 app/services。

错误码映射（contracts/api/README.md）：
解析失败 422 / 实体歧义 409 / 模型失败 503 / 校验失败 400 / 未认证 401 /
**无权限 404**（不是 403：403 会暴露对象存在性，可用于枚举他人研究覆盖）。
"""

from __future__ import annotations

from typing import TypeVar
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.ai.gateway import Gateway, ModelUnavailable
from app.api.deps import ActorDep, SettingsDep, UowDep
from app.core.domain import ThesisRecord, UnitOfWork
from app.core.enums import ImpactDirection, ThesisStatus
from app.schemas.thesis import (
    EvidenceActionIn,
    EvidenceOut,
    HypothesisOut,
    StatusDecisionIn,
    SuggestionOut,
    ThesisDraftIn,
    ThesisOut,
    ThesisPublishIn,
)
from app.services import audit, permission
from app.services import evidence as evidence_service
from app.services import status as status_service
from app.services import thesis as thesis_service
from app.services.errors import (
    EntityAmbiguous,
    HumanGateRequired,
    IllegalTransition,
    NotVisible,
    ValidationFailed,
)
from app.services.permission import Actor

E = TypeVar("E", ThesisStatus, ImpactDirection)

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
            )
            for h in hypotheses
        ],
    )


@router.post("/theses/drafts", response_model=ThesisOut, status_code=201)
def create_draft(
    payload: ThesisDraftIn,
    actor: ActorDep,
    uow: UowDep,
    conf: SettingsDep,
) -> ThesisOut:
    """从观点生成卡片草稿（FR-T-001 / FR-T-002）。草稿不会自动发布。"""
    try:
        gateway = Gateway.build(conf)
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        outcome = gateway.thesis_draft(
            security_id=payload.security_id,
            view=payload.view,
            segments=[],
            source_document_id=payload.document_id,
        )
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not outcome.usable:
        raise HTTPException(
            status_code=422,
            detail={"code": "AI_OUTPUT_INVALID", "errors": outcome.errors[:5]},
        )

    # 用 uuid4 而不是 hash(view)：CPython 的字符串 hash 按进程随机化，同一观点
    # 换个进程就变 ID；同进程内重复建卡又会撞主键，flush 抛 IntegrityError 变 500。
    thesis_id = f"THS-{payload.security_id}-{uuid4().hex[:12]}"
    try:
        thesis_service.create_draft(uow, thesis_id=thesis_id, draft=outcome.payload, actor=actor)
    except EntityAmbiguous as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "ENTITY_AMBIGUOUS", "candidates": exc.candidates},
        ) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _to_out(uow, thesis_id)


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
