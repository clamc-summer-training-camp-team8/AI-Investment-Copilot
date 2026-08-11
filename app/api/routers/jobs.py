"""Document-upload and asynchronous-job endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.deps import ActorDep, SettingsDep
from app.schemas.job import JobAcceptedOut, JobStatusOut
from app.workers.queue import (
    JobNotVisible,
    QueueUnavailable,
    enqueue_document,
    job_snapshot,
    open_queue,
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
    if bool(thesis_id) != bool(security_id):
        raise HTTPException(status_code=422, detail="thesis_id 与 security_id 必须同时提供")
    if len(view) > 2000:
        raise HTTPException(status_code=422, detail="view 最长 2000 个字符")
    document_id = f"DOC-{uuid4().hex}"
    path = (conf.storage_dir / "uploads" / f"{document_id}{suffix}").resolve()
    await _save_upload(file, path, conf.upload_max_bytes)

    redis = None
    try:
        redis = await open_queue(conf)
        job_id = await enqueue_document(
            redis,
            document_id=document_id,
            path=str(path),
            actor=actor,
            published_at=published_at,
            thesis_id=thesis_id,
            security_id=security_id,
            view=view,
        )
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if redis is not None:
            await redis.aclose()
    return JobAcceptedOut(job_id=job_id, document_id=document_id)


@router.get("/{job_id}", response_model=JobStatusOut)
async def get_job(job_id: str, actor: ActorDep, conf: SettingsDep) -> JobStatusOut:
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
