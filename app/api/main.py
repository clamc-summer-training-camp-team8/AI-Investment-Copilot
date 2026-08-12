"""FastAPI 应用装配。

路由按 PRD 6.1 的一级导航分组，注册在 app/api/routers/ 下。

这一层刻意保持很薄：解析请求、取身份、调一个 service、组装响应。
出现业务分支判断说明代码放错了模块，应当移到 app/services。
"""

from __future__ import annotations

from fastapi import FastAPI

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

    @application.get("/health", tags=["infra"])
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    from app.api.routers import demo, radar, reviews, thesis, workbench

    application.include_router(demo.router, prefix="/api")
    application.include_router(thesis.router, prefix="/api")
    application.include_router(workbench.router, prefix="/api")
    application.include_router(radar.router, prefix="/api")
    application.include_router(reviews.router, prefix="/api")

    # 其余路由在各自模块实现后在此注册：
    # application.include_router(radar.router, prefix="/api/radar")
    # application.include_router(admin.router, prefix="/api/admin")

    return application


app = create_app()
