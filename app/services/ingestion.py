"""持久化资料任务、死信重放、证券候选和统一人工复核。"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.core.domain import (
    DocumentProcessingJobRecord,
    IngestionReviewRecord,
    UnitOfWork,
)
from app.core.timeutil import now
from app.services import audit
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor

FINAL_STATUSES = {"succeeded", "failed", "dead_letter"}
REPLAYABLE_STATUSES = {"failed", "dead_letter"}


def create_job(
    uow: UnitOfWork,
    *,
    job_id: str,
    document_id: str,
    path: Path | None,
    source_filename: str,
    actor: Actor,
    published_at: datetime | None,
    security_id: str | None,
    thesis_id: str | None,
    view: str,
    max_attempts: int = 3,
    revision_id: str | None = None,
    object_key: str | None = None,
    object_version_id: str | None = None,
    upload_content_hash: str | None = None,
    ingestion_run_id: str | None = None,
) -> DocumentProcessingJobRecord:
    record = DocumentProcessingJobRecord(
        job_id=job_id,
        document_id=document_id,
        owner=actor.user_id,
        actor_teams=sorted(actor.teams),
        upload_path=str(path) if path else None,
        source_filename=source_filename,
        published_at=published_at,
        security_id=security_id,
        thesis_id=thesis_id,
        view=view,
        max_attempts=max_attempts,
        revision_id=revision_id,
        object_key=object_key,
        object_version_id=object_version_id,
        upload_content_hash=upload_content_hash,
        ingestion_run_id=ingestion_run_id,
    )
    uow.processing_jobs.add(record)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CREATE,
        object_type="document_processing_job",
        object_id=job_id,
        detail={"document_id": document_id, "source_filename": source_filename},
    )
    return record


def get_job(uow: UnitOfWork, *, job_id: str, actor: Actor) -> DocumentProcessingJobRecord:
    record = uow.processing_jobs.get(job_id)
    if record is None or record.owner != actor.user_id:
        raise NotVisible("任务不存在或无访问权限")
    return record


def list_jobs(
    uow: UnitOfWork, *, actor: Actor, status: str | None = None, limit: int = 100
) -> list[DocumentProcessingJobRecord]:
    return uow.processing_jobs.list_for_owner(actor.user_id, status=status, limit=limit)


def mark_running(uow: UnitOfWork, job_id: str, *, attempt_count: int | None = None) -> None:
    record = uow.processing_jobs.get(job_id)
    if record:
        uow.processing_jobs.update(
            replace(
                record,
                status="running",
                started_at=now(),
                attempt_count=attempt_count or record.attempt_count,
            )
        )


def mark_progress(
    uow: UnitOfWork,
    job_id: str,
    *,
    stage: str,
    detail: dict[str, object] | None = None,
) -> None:
    record = uow.processing_jobs.get(job_id)
    if record:
        result = dict(record.result or {})
        result.update(detail or {})
        result["stage"] = stage
        uow.processing_jobs.update(replace(record, result=result))


def mark_complete(
    uow: UnitOfWork,
    job_id: str,
    *,
    result: dict[str, object],
    success: bool,
    dead_letter: bool = False,
) -> None:
    record = uow.processing_jobs.get(job_id)
    if not record:
        return
    error = None if success else str(result.get("reason") or result.get("message") or "处理失败")
    status = "succeeded" if success else "dead_letter" if dead_letter else "failed"
    uow.processing_jobs.update(
        replace(record, status=status, result=result, last_error=error, finished_at=now())
    )


def mark_retrying(
    uow: UnitOfWork, job_id: str, *, reason: str, attempt_count: int | None = None
) -> None:
    record = uow.processing_jobs.get(job_id)
    if record:
        uow.processing_jobs.update(
            replace(
                record,
                status="retrying",
                last_error=reason,
                attempt_count=attempt_count or record.attempt_count,
            )
        )


def build_replay(
    uow: UnitOfWork,
    *,
    source: DocumentProcessingJobRecord,
    actor: Actor,
) -> DocumentProcessingJobRecord:
    if source.owner != actor.user_id:
        raise NotVisible("任务不存在或无访问权限")
    if source.status not in REPLAYABLE_STATUSES:
        raise ValidationFailed("只有失败或死信任务可以重放")
    if not source.object_key and (not source.upload_path or not Path(source.upload_path).is_file()):
        raise ValidationFailed("原始上传文件已清理，无法重放；请重新上传")
    suffix = uuid4().hex[:12]
    replay = replace(
        source,
        job_id=f"document-{source.document_id}-r-{suffix}",
        status="queued",
        attempt_count=source.attempt_count + 1,
        result=None,
        last_error=None,
        created_at=None,
        started_at=None,
        finished_at=None,
        updated_at=None,
    )
    uow.processing_jobs.add(replay)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="重放任务",
        object_type="document_processing_job",
        object_id=replay.job_id,
        detail={"source_job_id": source.job_id, "document_id": source.document_id},
    )
    return replay


def build_assignment_replay(
    uow: UnitOfWork,
    *,
    source: DocumentProcessingJobRecord,
    security_id: str,
    actor: Actor,
) -> DocumentProcessingJobRecord:
    if source.owner != actor.user_id:
        raise NotVisible("任务不存在或无访问权限")
    if not source.object_key and (not source.upload_path or not Path(source.upload_path).is_file()):
        raise ValidationFailed("原始上传文件已清理，无法按证券重新处理")
    replay = replace(
        source,
        job_id=f"document-{source.document_id}-a-{uuid4().hex[:12]}",
        security_id=security_id,
        status="queued",
        attempt_count=source.attempt_count + 1,
        result=None,
        last_error=None,
        created_at=None,
        started_at=None,
        finished_at=None,
        updated_at=None,
    )
    uow.processing_jobs.add(replay)
    return replay


def suggest_securities(
    uow: UnitOfWork, *, title: str | None, segments: list[tuple[str, str]], limit: int = 5
) -> list[dict[str, object]]:
    text = " ".join([title or "", *(content for _, content in segments)]).lower()
    scored: list[tuple[int, str, str, list[str]]] = []
    for security in uow.securities.search(None, limit=1000):
        terms = {
            security.security_id.lower(),
            security.name.lower(),
            *((security.ticker or "").lower(),),
            *(alias.lower() for alias in security.aliases),
        }
        matched = sorted(term for term in terms if term and _term_occurs(text, term))
        if matched:
            score = sum(4 if term == security.security_id.lower() else 3 for term in matched)
            scored.append((score, security.security_id, security.name, matched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"security_id": security_id, "name": name, "score": score, "matched_terms": matched}
        for score, security_id, name, matched in scored[:limit]
    ]


def _term_occurs(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9.]+", term):
        return re.search(rf"(?<![a-z0-9.]){re.escape(term)}(?![a-z0-9.])", text) is not None
    return term in text


def create_review(
    uow: UnitOfWork,
    *,
    review_type: str,
    document_id: str,
    reason: str,
    actor: Actor,
    job_id: str | None = None,
    event_id: str | None = None,
    payload: dict[str, object] | None = None,
    security_candidates: list[dict[str, object]] | None = None,
) -> IngestionReviewRecord:
    dedupe_key = f"{review_type}:{event_id or document_id}"
    existing = uow.ingestion_reviews.get_by_dedupe_key(dedupe_key)
    if existing:
        return existing
    return uow.ingestion_reviews.add(
        IngestionReviewRecord(
            review_id=f"IRV-{uuid4().hex}",
            dedupe_key=dedupe_key,
            review_type=review_type,
            document_id=document_id,
            job_id=job_id,
            event_id=event_id,
            reason=reason,
            assignee=actor.user_id,
            payload=payload or {},
            security_candidates=security_candidates or [],
        )
    )


def list_reviews(
    uow: UnitOfWork, *, actor: Actor, status: str | None = None, limit: int = 100
) -> list[IngestionReviewRecord]:
    return uow.ingestion_reviews.list_for_assignee(actor.user_id, status=status, limit=limit)


def resolve_review(
    uow: UnitOfWork,
    *,
    review_id: str,
    actor: Actor,
    resolution: str,
    security_id: str | None = None,
) -> IngestionReviewRecord:
    record = uow.ingestion_reviews.get(review_id)
    if record is None or record.assignee != actor.user_id:
        raise NotVisible("资料复核项不存在或无访问权限")
    if record.status != "pending":
        raise ValidationFailed("资料复核项已经完成")
    if len(resolution.strip()) < 2:
        raise ValidationFailed("复核结论不能为空")
    if security_id:
        if uow.securities.get(security_id) is None:
            raise ValidationFailed("候选证券不存在")
        document = uow.documents.get(record.document_id)
        if document and document.security_id and document.security_id != security_id:
            raise ValidationFailed("文档已归属其他证券，不能直接覆盖")
        if document:
            uow.documents.update_security(record.document_id, security_id)
    updated = replace(
        record,
        status="resolved",
        resolution=resolution.strip(),
        resolved_by=actor.user_id,
        resolved_at=now(),
    )
    uow.ingestion_reviews.update(updated)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action=audit.CONFIRM,
        object_type="ingestion_review",
        object_id=review_id,
        detail={"resolution": resolution.strip(), "security_id": security_id},
    )
    return updated
