"""ARQ worker configuration.

Run with: ``arq app.workers.settings.WorkerSettings``.
"""

from __future__ import annotations

import os
import time
from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import cron

from app.core.config import settings
from app.workers.company_metric_sync import sync_company_metrics_daily_job
from app.workers.eastmoney_sync import sync_eastmoney_daily_job
from app.workers.jobs import (
    analyze_document_job,
    cleanup_uploads_job,
    process_document_job,
    recover_stale_jobs,
)
from app.workers.news_collection import collect_investoday_news_job, collect_investoday_reports_job
from app.workers.queue import WORKER_HEALTH_KEY

# ARQ 的 cron 使用 worker 进程的本地时钟。开发机、容器和服务器必须对齐到
# 业务日（而不是服务器可能使用的 UTC）；Linux 上 tzset 会立即生效，Windows
# 本地开发仍沿用系统时区。
if os.environ.get("TZ") != settings.app_timezone:
    os.environ["TZ"] = settings.app_timezone
    if hasattr(time, "tzset"):
        time.tzset()


class WorkerSettings:
    functions: ClassVar[list[object]] = [
        process_document_job,
        analyze_document_job,
        cleanup_uploads_job,
        recover_stale_jobs,
        sync_eastmoney_daily_job,
        sync_company_metrics_daily_job,
        collect_investoday_news_job,
        collect_investoday_reports_job,
    ]
    cron_jobs: ClassVar[list[object]] = [
        cron(cleanup_uploads_job, hour=3, minute=15),
        cron(recover_stale_jobs, minute={0, 15, 30, 45}, run_at_startup=True),
        cron(sync_eastmoney_daily_job, hour=4, minute=0),
        cron(sync_company_metrics_daily_job, hour=18, minute=10),
        # 工作日的开盘前预采集 + 盘中/盘后补采集。任务重启时也会补跑一轮，
        # 由供应商条目 ID 去重，因此研究员早上打开工作台不会依赖手动点击。
        cron(
            collect_investoday_news_job,
            weekday={0, 1, 2, 3, 4},
            hour={7, 9, 12, 15, 18},
            minute=5,
            run_at_startup=True,
        ),
        cron(
            collect_investoday_reports_job,
            weekday={0, 1, 2, 3, 4},
            hour={7, 18},
            minute=20,
            run_at_startup=True,
        ),
        # 20:30 补齐收盘后发布的研报，避免研究员等到次日早间才能看到。
        cron(
            collect_investoday_reports_job,
            weekday={0, 1, 2, 3, 4},
            hour=20,
            minute=30,
        ),
    ]
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 10
    # 真实模型分析包含事件抽取、关系推理与日内归并；必须大于单段模型超时，
    # 否则 ARQ 会在应用层来得及记录“分析超时”前强行取消任务。
    job_timeout = max(900, int(settings.llm_analysis_timeout_seconds * 3 + 60))
    # 文档解析成功后，模型失败应由“重新分析”显式触发；禁止 ARQ 从头解析文档。
    max_tries = 1
    keep_result = 3600
    retry_jobs = False
    # API readiness and the local bootstrap script use this short-lived key to
    # distinguish "Redis is reachable" from "a worker can actually run jobs".
    health_check_interval = 5
    health_check_key = WORKER_HEALTH_KEY
