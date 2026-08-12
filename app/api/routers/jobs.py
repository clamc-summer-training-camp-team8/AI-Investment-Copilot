"""Document-upload and asynchronous-job endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import ActorDep, SettingsDep, UowDep
from app.core.domain import DocumentProcessingJobRecord
from app.schemas.job import JobAcceptedOut, JobStatusOut, ProcessingJobOut
from app.services import assets as asset_service
from app.services import ingestion as ingestion_service
from app.services import security as security_service
from app.services.errors import NotVisible, ValidationFailed
from app.services.object_store import ObjectStoreError, S3ObjectStore
from app.workers.queue import (
    JobNotVisible,
    QueueUnavailable,
    enqueue_document,
    enqueue_job_record,
    job_snapshot,
    open_queue,
    worker_ready,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])
ALLOWED_SUFFIXES = {".txt", ".pdf", ".docx"}


async def _save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> None:
    size = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="上传文件超过大小限制")
                handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


@router.post("/documents", response_model=JobAcceptedOut, status_code=202)
async def upload_document(
    actor: ActorDep,
    conf: SettingsDep,
    uow: UowDep,
    file: Annotated[UploadFile, File()],
    published_at: Annotated[datetime | None, Form()] = None,
    thesis_id: Annotated[str | None, Form()] = None,
    security_id: Annotated[str | None, Form()] = None,
    view: Annotated[str, Form()] = "",
) -> JobAcceptedOut:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="仅支持 PDF、DOCX 和 TXT")
    if published_at is not None and (
        published_at.tzinfo is None or published_at.utcoffset() is None
    ):
        raise HTTPException(status_code=422, detail="published_at 必须包含时区")
    if thesis_id and not security_id:
        raise HTTPException(status_code=422, detail="关联逻辑时必须同时提供 security_id")
    if security_id:
        try:
            security_id = security_service.require(uow, security_id).security_id
        except ValidationFailed as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if thesis_id:
        thesis = uow.thesis.get(thesis_id)
        if thesis is None or thesis.security_id != security_id:
            raise HTTPException(status_code=400, detail="关联逻辑不存在或与所选证券不一致")
    if len(view) > 2000:
        raise HTTPException(status_code=422, detail="view 最长 2000 个字符")
    document_id = f"DOC-{uuid4().hex}"
    path = (conf.storage_dir / "uploads" / f"{document_id}{suffix}").resolve()
    job_id = f"document-{document_id}"

    redis = None
    try:
        redis = await open_queue(conf)
        if not await worker_ready(redis):
            raise QueueUnavailable("任务处理器不可用，请先启动 ARQ worker")
        # 健康检查通过后才把原文写入上传目录，避免队列不可用时
        # 反复留下无任务指向的孤儿文件。
        await _save_upload(file, path, conf.upload_max_bytes)
        object_store = S3ObjectStore(conf)
        await asyncio.to_thread(object_store.ensure_bucket)
        revision, duplicate_revision = await asyncio.to_thread(
            asset_service.archive_upload,
            uow,
            path=path,
            document_id=document_id,
            source_filename=Path(file.filename or path.name).name,
            media_type=file.content_type,
            published_at=published_at,
            actor=actor,
            object_store=object_store,
        )
        if duplicate_revision:
            document_id = revision.canonical_document_id or revision.document_id
            job_id = f"document-{document_id}-replay-{uuid4().hex[:12]}"
        run = asset_service.create_run(uow, revision_id=revision.revision_id, settings=conf)
        ingestion_service.create_job(
            uow,
            job_id=job_id,
            document_id=document_id,
            path=None,
            source_filename=Path(file.filename or path.name).name,
            actor=actor,
            published_at=published_at,
            security_id=security_id,
            thesis_id=thesis_id,
            view=view,
            revision_id=revision.revision_id,
            object_key=revision.object_key,
            object_version_id=revision.object_version_id,
            upload_content_hash=revision.content_hash,
            ingestion_run_id=run.run_id,
        )
        job_id = await enqueue_document(
            redis,
            document_id=document_id,
            path="",
            actor=actor,
            published_at=published_at,
            thesis_id=thesis_id,
            security_id=security_id,
            view=view,
            revision_id=revision.revision_id,
            object_key=revision.object_key,
            object_version_id=revision.object_version_id,
            upload_content_hash=revision.content_hash,
            ingestion_run_id=run.run_id,
            source_filename=Path(file.filename or path.name).name,
            job_id=job_id,
        )
    except (QueueUnavailable, ObjectStoreError) as exc:
        path.unlink(missing_ok=True)
        ingestion_service.mark_complete(
            uow,
            job_id,
            result={"ok": False, "document_id": document_id, "reason": str(exc)},
            success=False,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        ingestion_service.mark_complete(
            uow,
            job_id,
            result={"ok": False, "document_id": document_id, "reason": "任务入队失败"},
            success=False,
        )
        raise HTTPException(status_code=503, detail="任务入队失败，请检查 Redis 与 worker") from exc
    finally:
        if redis is not None:
            await redis.aclose()
    return JobAcceptedOut(job_id=job_id, document_id=document_id)


def _processing_out(record: DocumentProcessingJobRecord) -> ProcessingJobOut:
    return ProcessingJobOut(
        job_id=record.job_id,
        document_id=record.document_id,
        source_filename=record.source_filename,
        security_id=record.security_id,
        status=record.status,
        attempt_count=record.attempt_count,
        max_attempts=record.max_attempts,
        result=record.result,
        last_error=record.last_error,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


@router.get("", response_model=list[ProcessingJobOut])
def list_jobs(
    actor: ActorDep,
    uow: UowDep,
    status: str | None = None,
    limit: int = 100,
) -> list[ProcessingJobOut]:
    return [
        _processing_out(record)
        for record in ingestion_service.list_jobs(
            uow, actor=actor, status=status, limit=min(max(limit, 1), 200)
        )
    ]


@router.post("/{job_id}/replay", response_model=JobAcceptedOut, status_code=202)
async def replay_job(
    job_id: str, actor: ActorDep, conf: SettingsDep, uow: UowDep
) -> JobAcceptedOut:
    try:
        source = ingestion_service.get_job(uow, job_id=job_id, actor=actor)
    except NotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    redis = None
    try:
        redis = await open_queue(conf)
        if not await worker_ready(redis):
            raise QueueUnavailable("任务处理器不可用，请先启动 ARQ worker")
        replay = ingestion_service.build_replay(uow, source=source, actor=actor)
        await enqueue_job_record(redis, replay)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if redis is not None:
            await redis.aclose()
    return JobAcceptedOut(job_id=replay.job_id, document_id=replay.document_id)


@router.get("/{job_id}", response_model=JobStatusOut)
async def get_job(job_id: str, actor: ActorDep, conf: SettingsDep, uow: UowDep) -> JobStatusOut:
    persisted = uow.processing_jobs.get(job_id)
    if persisted is not None:
        if persisted.owner != actor.user_id:
            raise HTTPException(status_code=404, detail="任务不存在或无访问权限")
        if persisted.status in ingestion_service.FINAL_STATUSES:
            return JobStatusOut(
                job_id=job_id,
                status="complete",
                success=persisted.status == "succeeded",
                result=persisted.result,
                start_time=persisted.started_at,
                finish_time=persisted.finished_at,
            )
    redis = None
    try:
        redis = await open_queue(conf)
        snapshot = await job_snapshot(redis, job_id, actor_id=actor.user_id)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JobNotVisible as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        if redis is not None:
            await redis.aclose()
    return JobStatusOut(**snapshot)
