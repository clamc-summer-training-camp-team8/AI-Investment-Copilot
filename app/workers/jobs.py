"""可恢复的 ARQ 后台任务入口。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from arq import Retry

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings
from app.services.ai_runtime import SqlRuntimeRecorder
from app.services.permission import Actor
from app.services.uow import uow_scope
from app.workers.document_chain import draft_from_document, process_document


def _published_at(raw: str | None) -> datetime | None:
    return None if raw is None else datetime.fromisoformat(raw)


def _safe_upload_path(path: str, settings: Settings) -> Path:
    resolved = Path(path).resolve()
    root = (settings.storage_dir / "uploads").resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("任务文件不在受控上传目录")
    return resolved


async def process_document_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    settings = Settings()
    document_id = str(payload["document_id"])
    path = _safe_upload_path(str(payload["path"]), settings)
    actor = Actor(
        user_id=str(payload["actor_id"]),
        teams=frozenset(str(item) for item in payload.get("actor_teams", [])),
    )
    result = await asyncio.to_thread(
        process_document,
        document_id=document_id,
        path=path,
        published_at=_published_at(payload.get("published_at")),
    )
    if not result.ok:
        return {
            "ok": False,
            "document_id": document_id,
            "reason": result.failure_reason or "文档处理失败",
            "manual_review": True,
        }

    draft: dict[str, object] | None = None
    if payload.get("thesis_id") and payload.get("security_id"):
        runtime = InvestmentResearchAgent.build(
            Gateway.build(settings),
            recorder=SqlRuntimeRecorder(),
        )
        try:
            with uow_scope() as uow:
                draft = draft_from_document(
                    uow,
                    runtime,
                    thesis_id=str(payload["thesis_id"]),
                    security_id=str(payload["security_id"]),
                    view=str(payload.get("view") or ""),
                    result=result,
                    actor=actor,
                )
        except ModelUnavailable as exc:
            job_try = int(ctx.get("job_try", 1))
            max_tries = int(ctx.get("max_tries", settings.runtime_max_attempts))
            if exc.retryable and job_try < max_tries:
                raise Retry(defer=min(5 * (2 ** (job_try - 1)), 60)) from exc
            return {
                "ok": False,
                "document_id": document_id,
                "reason": str(exc),
                "manual_review": True,
                "retry_exhausted": True,
            }

    return {
        "ok": True,
        "document_id": document_id,
        "segment_count": len(result.segments),
        "content_hash": result.content_hash,
        "parser_version": result.parser_version,
        "draft_created": draft is not None,
    }
