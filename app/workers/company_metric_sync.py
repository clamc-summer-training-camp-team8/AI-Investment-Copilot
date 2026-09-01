"""企业指标中心每日增量同步任务。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.services.company_metric_center import refresh_security_metrics
from app.services.uow import uow_scope


async def sync_company_metrics_daily_job(ctx: dict[str, Any]) -> dict[str, Any]:
    del ctx
    with uow_scope() as uow:
        security_ids = [item.security_id for item in uow.securities.search(None, limit=200)]
    results = []
    for security_id in security_ids:
        results.append(await asyncio.to_thread(_refresh_one, security_id))
    return {
        "ok": not any(item["errors"] for item in results),
        "securities": len(results),
        "inserted": sum(int(item["inserted"]) for item in results),
        "results": results,
    }


def _refresh_one(security_id: str) -> dict[str, Any]:
    with uow_scope() as uow:
        return refresh_security_metrics(uow, security_id)
