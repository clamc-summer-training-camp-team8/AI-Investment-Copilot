"""Queue client used by HTTP endpoints without exposing ARQ to the API layer."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job

from app.core.config import Settings
from app.core.domain import DocumentProcessingJobRecord
from app.services.permission import Actor


class QueueUnavailable(RuntimeError):
    pass


class JobNotVisible(LookupError):
    pass


WORKER_HEALTH_KEY = "copilot:worker:health"


async def open_queue(settings: Settings) -> ArqRedis:
    try:
        redis_settings = replace(
            RedisSettings.from_dsn(settings.redis_url),
            conn_timeout=1,
            conn_retries=0,
        )
        return await create_pool(redis_settings, retry=0)
    except Exception as exc:
        raise QueueUnavailable("任务队列不可用，请确认 Redis 已启动") from exc


async def worker_ready(redis: ArqRedis) -> bool:
    """Return whether an ARQ worker has refreshed its short-lived sentinel."""

    return bool(await redis.get(WORKER_HEALTH_KEY))


async def enqueue_document(
    redis: ArqRedis,
    *,
    document_id: str,
    path: str,
    actor: Actor,
    published_at: datetime | None = None,
    thesis_id: str | None = None,
    security_id: str | None = None,
    view: str = "",
    revision_id: str | None = None,
    object_key: str | None = None,
    object_version_id: str | None = None,
    upload_content_hash: str | None = None,
    ingestion_run_id: str | None = None,
    source_filename: str | None = None,
    job_id: str | None = None,
) -> str:
    job_id = job_id or f"document-{document_id}"
    payload = {
        "job_id": job_id,
        "document_id": document_id,
        "path": path,
        "published_at": published_at.isoformat() if published_at else None,
        "thesis_id": thesis_id,
        "security_id": security_id,
        "view": view,
        "actor_id": actor.user_id,
        "actor_teams": sorted(actor.teams),
        "revision_id": revision_id,
        "object_key": object_key,
        "object_version_id": object_version_id,
        "upload_content_hash": upload_content_hash,
        "ingestion_run_id": ingestion_run_id,
        "source_filename": source_filename,
    }
    await redis.enqueue_job("process_document_job", payload, _job_id=job_id)
    await redis.set(f"job-owner:{job_id}", actor.user_id, ex=86400, nx=True)
    return job_id


async def enqueue_job_record(
    redis: ArqRedis,
    record: DocumentProcessingJobRecord,
    *,
    analysis_only: bool = False,
) -> str:
    """把 PostgreSQL 中的任务投递到执行队列；重放使用新的 job_id。"""
    payload = {
        "job_id": record.job_id,
        "document_id": record.document_id,
        "path": record.upload_path,
        "published_at": record.published_at.isoformat() if record.published_at else None,
        "thesis_id": record.thesis_id,
        "security_id": record.security_id,
        "view": record.view,
        "actor_id": record.owner,
        "actor_teams": record.actor_teams,
        "attempt_count": record.attempt_count,
        "max_attempts": record.max_attempts,
        "revision_id": record.revision_id,
        "object_key": record.object_key,
        "object_version_id": record.object_version_id,
        "upload_content_hash": record.upload_content_hash,
        "ingestion_run_id": record.ingestion_run_id,
        "source_filename": record.source_filename,
        "analysis_only": analysis_only,
    }
    function = "analyze_document_job" if analysis_only else "process_document_job"
    await redis.enqueue_job(function, payload, _job_id=record.job_id)
    await redis.set(f"job-owner:{record.job_id}", record.owner, ex=86400, nx=True)
    return record.job_id


async def job_snapshot(redis: ArqRedis, job_id: str, *, actor_id: str) -> dict[str, Any]:
    owner = await redis.get(f"job-owner:{job_id}")
    decoded_owner = owner.decode() if isinstance(owner, bytes) else owner
    if decoded_owner != actor_id:
        raise JobNotVisible("任务不存在或无访问权限")
    job = Job(job_id, redis)
    status = await job.status()
    result = await job.result_info()
    result_value: Any = None if result is None else result.result
    if isinstance(result_value, BaseException):
        result_value = {
            "error": type(result_value).__name__,
            "message": str(result_value),
        }
    return {
        "job_id": job_id,
        "status": status.value,
        "success": None if result is None else result.success,
        "result": result_value,
        "enqueue_time": None if result is None else result.enqueue_time,
        "start_time": None if result is None else result.start_time,
        "finish_time": None if result is None else result.finish_time,
    }
