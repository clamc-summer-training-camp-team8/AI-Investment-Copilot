"""Operator endpoints for bounded external-source collection."""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.api.deps import ActorDep, SettingsDep
from app.workers.news_collection import collection_business_day, collection_status_key
from app.workers.queue import QueueUnavailable, open_queue, worker_ready

router = APIRouter(prefix="/collection", tags=["collection"])


async def _status_for_kind(
    redis: object, *, kind: str, business_day: str, enabled: bool
) -> dict[str, object]:
    """Return an operator-safe view of today's source-collection checkpoint."""

    if not enabled:
        return {
            "kind": kind,
            "status": "disabled",
            "business_date": business_day,
            "is_current": True,
        }
    raw = await redis.get(collection_status_key(kind))  # type: ignore[union-attr]
    if raw is None:
        return {
            "kind": kind,
            "status": "not_started",
            "business_date": business_day,
            "is_current": False,
        }
    try:
        payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except (TypeError, ValueError):
        return {
            "kind": kind,
            "status": "not_started",
            "business_date": business_day,
            "is_current": False,
        }
    if not isinstance(payload, dict) or payload.get("business_date") != business_day:
        return {
            "kind": kind,
            "status": "not_started",
            "business_date": business_day,
            "is_current": False,
        }
    return {
        "kind": kind,
        "status": str(payload.get("status", "not_started")),
        "business_date": business_day,
        "is_current": True,
        "updated_at": payload.get("updated_at"),
        "fetched": int(payload.get("fetched", 0) or 0),
        "queued": int(payload.get("queued", 0) or 0),
        "queued_today": int(payload.get("queued_today", 0) or 0),
        "skipped_seen": int(payload.get("skipped_seen", 0) or 0),
    }


@router.get("/investoday/status")
async def investoday_collection_status(_actor: ActorDep, conf: SettingsDep) -> dict[str, object]:
    """Current business-day acquisition status for the research workbench.

    This only exposes operational counters. Source bodies and provider errors
    remain inside the protected ingestion pipeline.
    """

    business_day = collection_business_day(conf)
    news_enabled = conf.investoday_news_enabled and bool(conf.investoday_api_key)
    reports_enabled = conf.investoday_reports_enabled and bool(conf.investoday_api_key)
    redis = None
    try:
        redis = await open_queue(conf)
        ready = await worker_ready(redis)
        news = await _status_for_kind(
            redis, kind="news", business_day=business_day, enabled=news_enabled
        )
        reports = await _status_for_kind(
            redis, kind="report", business_day=business_day, enabled=reports_enabled
        )
        states = {str(news["status"]), str(reports["status"])}
        overall = (
            "failed"
            if "failed" in states
            else "running"
            if "running" in states
            else "completed"
            if states <= {"completed", "disabled"}
            else "not_started"
        )
        return {
            "business_date": business_day,
            "worker_ready": ready,
            "overall_status": overall,
            "news": news,
            "reports": reports,
        }
    except QueueUnavailable:
        return {
            "business_date": business_day,
            "worker_ready": False,
            "overall_status": "unavailable",
            "news": {
                "kind": "news",
                "status": "unavailable",
                "business_date": business_day,
                "is_current": False,
            },
            "reports": {
                "kind": "report",
                "status": "unavailable",
                "business_date": business_day,
                "is_current": False,
            },
        }
    finally:
        if redis is not None:
            await redis.aclose()


@router.post("/investoday/news/sync", status_code=202)
async def sync_investoday_news(actor: ActorDep, conf: SettingsDep) -> dict[str, str]:
    """Queue one manually requested, bounded collection run.

    It intentionally does not return provider data, so neither raw content nor
    credentials can leak through the control-plane endpoint.
    """

    if not conf.investoday_news_enabled or not conf.investoday_api_key:
        raise HTTPException(status_code=409, detail="今日投资新闻采集尚未启用或未配置密钥")
    redis = None
    try:
        redis = await open_queue(conf)
        if not await worker_ready(redis):
            raise QueueUnavailable("任务处理器不可用，请先启动 ARQ worker")
        job_id = f"collect-investoday-news-{uuid4().hex[:12]}"
        await redis.enqueue_job("collect_investoday_news_job", _job_id=job_id)
        await redis.set(f"job-owner:{job_id}", actor.user_id, ex=86400, nx=True)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if redis is not None:
            await redis.aclose()
    return {"job_id": job_id, "status": "queued"}


@router.post("/investoday/reports/sync", status_code=202)
async def sync_investoday_reports(actor: ActorDep, conf: SettingsDep) -> dict[str, str]:
    """Queue one bounded, stock-code-targeted research-report collection run."""

    if not conf.investoday_reports_enabled or not conf.investoday_api_key:
        raise HTTPException(status_code=409, detail="今日投资研报采集尚未启用或未配置密钥")
    redis = None
    try:
        redis = await open_queue(conf)
        if not await worker_ready(redis):
            raise QueueUnavailable("任务处理器不可用，请先启动 ARQ worker")
        job_id = f"collect-investoday-reports-{uuid4().hex[:12]}"
        await redis.enqueue_job("collect_investoday_reports_job", _job_id=job_id)
        await redis.set(f"job-owner:{job_id}", actor.user_id, ex=86400, nx=True)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        if redis is not None:
            await redis.aclose()
    return {"job_id": job_id, "status": "queued"}
