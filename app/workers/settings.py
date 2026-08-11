"""ARQ worker configuration.

Run with: ``arq app.workers.settings.WorkerSettings``.
"""

from __future__ import annotations

from typing import ClassVar

from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.jobs import process_document_job


class WorkerSettings:
    functions: ClassVar[list[object]] = [process_document_job]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 180
    max_tries = 3
    keep_result = 3600
    retry_jobs = True
