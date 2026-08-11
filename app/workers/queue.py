"""API 与 ARQ 之间的稳定队列接口。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.jobs import Job

from app.core.config import Settings
from app.services.permission import Actor


class QueueUnavailable(RuntimeError):
    pass


class JobNotVisible(LookupError):
    pass


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
) -> str:
    """同一文档 ID 只产生一个队列任务，重复请求返回相同 job_id。"""
    job_id = f"document-{document_id}"
    payload = {
        "document_id": document_id,
        "path": path,
        "published_at": published_at.isoformat() if published_at else None,
        "thesis_id": thesis_id,
        "security_id": security_id,
        "view": view,
        "actor_id": actor.user_id,
        "actor_teams": sorted(actor.teams),
    }
    await redis.enqueue_job("process_document_job", payload, _job_id=job_id)
    await redis.set(f"job-owner:{job_id}", actor.user_id, ex=86400, nx=True)
    return job_id


async def job_snapshot(redis: ArqRedis, job_id: str, *, actor_id: str) -> dict[str, Any]:
    owner = await redis.get(f"job-owner:{job_id}")
    decoded_owner = owner.decode() if isinstance(owner, bytes) else owner
    if decoded_owner != actor_id:
        raise JobNotVisible("任务不存在或无访问权限")
    job = Job(job_id, redis)
    status = await job.status()
    result = await job.result_info()
    value: Any = None if result is None else result.result
    if isinstance(value, BaseException):
        value = {"error": type(value).__name__, "message": str(value)}
    return {
        "job_id": job_id,
        "status": status.value,
        "success": None if result is None else result.success,
        "result": value,
        "enqueue_time": None if result is None else result.enqueue_time,
        "start_time": None if result is None else result.start_time,
        "finish_time": None if result is None else result.finish_time,
    }
