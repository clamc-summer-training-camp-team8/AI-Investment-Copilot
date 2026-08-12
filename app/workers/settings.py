"""ARQ worker configuration.

Run with: ``arq app.workers.settings.WorkerSettings``.
"""

from __future__ import annotations

from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import settings
from app.workers.jobs import cleanup_uploads_job, process_document_job, recover_stale_jobs
from app.workers.queue import WORKER_HEALTH_KEY


class WorkerSettings:
    functions: ClassVar[list[object]] = [
        process_document_job,
        cleanup_uploads_job,
        recover_stale_jobs,
    ]
    cron_jobs: ClassVar[list[object]] = [
        cron(cleanup_uploads_job, hour=3, minute=15),
        cron(recover_stale_jobs, minute={0, 15, 30, 45}, run_at_startup=True),
    ]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    job_timeout = 180
    max_tries = 3
    keep_result = 3600
    retry_jobs = True
    # API readiness and the local bootstrap script use this short-lived key to
    # distinguish "Redis is reachable" from "a worker can actually run jobs".
    health_check_interval = 5
    health_check_key = WORKER_HEALTH_KEY
