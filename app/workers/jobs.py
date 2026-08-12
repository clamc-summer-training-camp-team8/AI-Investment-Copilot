"""ARQ job entry points for durable asynchronous document processing."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from arq import Retry

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.core.config import Settings
from app.ingest.facts import extract_key_facts
from app.services import document as document_service
from app.services.permission import Actor
from app.services.review import create_task
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


def _create_failure_review(
    *,
    thesis_id: str | None,
    actor: Actor,
    document_id: str,
    reason: str,
) -> None:
    if not thesis_id:
        return
    with uow_scope() as uow:
        create_task(
            uow,
            thesis_id=thesis_id,
            trigger="处理失败",
            priority="高",
            assignee=actor.user_id,
            actor=actor,
            detail={"document_id": document_id, "reason": reason},
        )


async def process_document_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Parse a stored document and optionally create a thesis draft."""
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
        reason = result.failure_reason or "文档处理失败"
        _create_failure_review(
            thesis_id=payload.get("thesis_id"),
            actor=actor,
            document_id=document_id,
            reason=reason,
        )
        return {"ok": False, "document_id": document_id, "reason": reason, "manual_review": True}

    facts = extract_key_facts(result.segments)
    with uow_scope() as uow:
        persisted = document_service.persist_processed(
            uow,
            document_id=result.document_id,
            title=result.title,
            doc_type=result.doc_type,
            published_at=result.published_at,
            content_hash=result.content_hash,
            parser_version=result.parser_version,
            segments=result.segments,
            path=path,
            actor=actor,
            security_id=str(payload["security_id"]) if payload.get("security_id") else None,
            facts=facts,
        )

    draft: dict[str, object] | None = None
    if (
        payload.get("thesis_id")
        and payload.get("security_id")
        and persisted.document_id == document_id
    ):
        try:
            gateway = Gateway.build(settings)
            with uow_scope() as uow:
                draft = draft_from_document(
                    uow,
                    gateway,
                    thesis_id=str(payload["thesis_id"]),
                    security_id=str(payload["security_id"]),
                    view=str(payload.get("view") or ""),
                    result=result,
                    actor=actor,
                )
        except ModelUnavailable as exc:
            job_try = int(ctx.get("job_try", 1))
            max_tries = int(ctx.get("max_tries", 3))
            if exc.retryable and job_try < max_tries:
                raise Retry(defer=min(5 * (2 ** (job_try - 1)), 60)) from exc
            _create_failure_review(
                thesis_id=str(payload["thesis_id"]),
                actor=actor,
                document_id=document_id,
                reason=str(exc),
            )
            return {
                "ok": False,
                "document_id": document_id,
                "reason": str(exc),
                "manual_review": True,
            }

    return {
        "ok": True,
        "document_id": document_id,
        "persisted_document_id": persisted.document_id,
        "duplicate": persisted.document_id != document_id,
        "segment_count": len(result.segments),
        "fact_count": len(facts),
        "content_hash": result.content_hash,
        "parser_version": result.parser_version,
        "draft_created": draft is not None,
    }
