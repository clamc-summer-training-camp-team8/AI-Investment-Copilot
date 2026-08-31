"""审计留痕（FR-A-003）。

记录查看、创建、编辑、确认、导出和模型调用，可按对象追踪。

**审计写入与业务写入在同一事务内。** 调用方在 `session_scope()` 里同时做两件事，
审计失败会让业务动作一起回滚。允许审计缺失等于放弃可追溯性（DA-AC-07）。
"""

from __future__ import annotations

from app.services.ports import AuditRecord, AuditRepo

VIEW = "查看"
CREATE = "创建"
EDIT = "编辑"
CONFIRM = "确认"
REJECT = "驳回"
PUBLISH = "发布"
STATUS_CHANGE = "状态变更"
MODEL_CALL = "模型调用"
EXPORT = "导出"


def record(
    repo: AuditRepo,
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id: str,
    detail: dict[str, object] | None = None,
    model_version: str | None = None,
) -> None:
    repo.add(
        AuditRecord(
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            detail=detail,
            model_version=model_version,
        )
    )


def record_model_call(
    repo: AuditRepo,
    *,
    actor: str,
    object_type: str,
    object_id: str,
    model_version: str,
    prompt_version: str,
    ai_status: str,
    model_metadata: dict[str, object] | None = None,
) -> None:
    """模型调用留痕。

    不记录提示词与请求体明文（PRD 12.1）：受限文档内容会进提示词，落盘明文等于
    绕过权限控制。只记版本号和结果状态，这已足够复现与追溯。
    """
    safe_metadata = {
        key: value
        for key, value in (model_metadata or {}).items()
        if key in {"provider", "request_id", "usage", "finish_reason"}
    }
    detail: dict[str, object] = {"prompt_version": prompt_version, "ai_status": ai_status}
    if safe_metadata:
        detail["model_metadata"] = safe_metadata
    record(
        repo,
        actor=actor,
        action=MODEL_CALL,
        object_type=object_type,
        object_id=object_id,
        detail=detail,
        model_version=model_version,
    )
