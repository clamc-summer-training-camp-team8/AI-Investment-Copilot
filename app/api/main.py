"""FastAPI 应用装配。

路由按 PRD 6.1 的一级导航分组，注册在 app/api/routers/ 下。

这一层刻意保持很薄：解析请求、取身份、调一个 service、组装响应。
出现业务分支判断说明代码放错了模块，应当移到 app/services。
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "主动权益投资逻辑智能协作平台。"
            "系统输出候选信号与状态建议，不产生任何交易、评级或调仓指令。"
        ),
        debug=settings.debug,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-User-Id", "X-User-Teams"],
    )

    @application.get("/health", tags=["infra"])
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    @application.get("/health/ready", tags=["infra"])
    async def readiness() -> JSONResponse:
        from app.services.health import database_ready
        from app.services.object_store import S3ObjectStore
        from app.workers.queue import QueueUnavailable, open_queue, worker_ready

        database_ok, database_detail = await asyncio.to_thread(database_ready)
        redis = None
        try:
            redis = await open_queue(settings)
            redis_ok = bool(await redis.ping())
            redis_detail = "ok" if redis_ok else "ping_failed"
            worker_ok = redis_ok and await worker_ready(redis)
            worker_detail = "ok" if worker_ok else "worker_sentinel_missing"
        except QueueUnavailable as exc:
            redis_ok, redis_detail = False, str(exc)
            worker_ok, worker_detail = False, "queue_unavailable"
        except Exception as exc:
            redis_ok, redis_detail = False, type(exc).__name__
            worker_ok, worker_detail = False, type(exc).__name__
        finally:
            if redis is not None:
                await redis.aclose()
        try:
            object_store_ok = await asyncio.to_thread(S3ObjectStore(settings).ready)
            object_store_detail = "ok"
        except Exception as exc:
            object_store_ok = False
            object_store_detail = type(exc).__name__
        ready = database_ok and redis_ok and worker_ok and object_store_ok
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "database": {"ready": database_ok, "detail": database_detail},
                "queue": {"ready": redis_ok, "detail": redis_detail},
                "worker": {"ready": worker_ok, "detail": worker_detail},
                "object_store": {
                    "ready": object_store_ok,
                    "detail": object_store_detail,
                },
            },
        )

    from app.api.routers import (
        assets,
        documents,
        jobs,
        metrics,
        radar,
        review,
        reviews,
        securities,
        thesis,
        workbench,
    )

    application.include_router(securities.router, prefix="/api")
    application.include_router(assets.router, prefix="/api")
    application.include_router(metrics.router, prefix="/api")
    application.include_router(thesis.router, prefix="/api")
    application.include_router(workbench.router, prefix="/api")
    application.include_router(radar.router, prefix="/api")
    application.include_router(documents.router, prefix="/api")
    # 静态路径 /reviews/adjudications 必须先于 review 中的 /reviews/{task_id}
    # 注册，否则 FastAPI 会把 "adjudications" 当作 task_id。
    application.include_router(reviews.router, prefix="/api")
    application.include_router(review.router, prefix="/api")
    application.include_router(jobs.router, prefix="/api")

    # 其余路由在各自模块实现后在此注册：
    # application.include_router(radar.router, prefix="/api/radar")
    # application.include_router(admin.router, prefix="/api/admin")

    return application


app = create_app()
