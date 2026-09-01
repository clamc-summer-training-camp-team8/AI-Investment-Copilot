"""Controlled external-news collection, feeding the existing document pipeline."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.collection.investoday import (
    InvestodayError,
    InvestodayNews,
    InvestodayNewsClient,
    InvestodayReport,
)
from app.core.config import Settings
from app.core.domain import SourceRecord, ThesisQuery
from app.services import assets as asset_service
from app.services import ingestion as ingestion_service
from app.services.object_store import S3ObjectStore
from app.services.permission import Actor
from app.services.uow import uow_scope
from app.workers.queue import enqueue_document

_SYSTEM_ACTOR = Actor(user_id="analyst-mvp", teams=frozenset({"asset-admin"}))
_DEDUPE_TTL_SECONDS = 180 * 24 * 60 * 60
_STATUS_TTL_SECONDS = 3 * 24 * 60 * 60
_STATUS_KEY_PREFIX = "copilot:collection:investoday:status"


def collection_status_key(kind: str) -> str:
    """Public key name shared by the worker and the read-only status endpoint."""

    return f"{_STATUS_KEY_PREFIX}:{kind}"


def collection_business_day(conf: Settings) -> str:
    return datetime.now(ZoneInfo(conf.app_timezone)).date().isoformat()


async def _write_collection_status(
    redis: Any,
    *,
    kind: str,
    conf: Settings,
    status: str,
    **details: object,
) -> None:
    """Keep a compact, non-sensitive execution checkpoint for the UI.

    The durable documents and their processing jobs remain in PostgreSQL; this
    short-lived Redis record only answers the operational question "has today's
    source collection run, and are documents now waiting for analysis?".
    """

    if redis is None:
        return
    now = datetime.now(ZoneInfo(conf.app_timezone))
    business_date = now.date().isoformat()
    previous: dict[str, object] = {}
    raw = await redis.get(collection_status_key(kind))
    if raw is not None:
        try:
            parsed = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            if isinstance(parsed, dict) and parsed.get("business_date") == business_date:
                previous = parsed
        except (TypeError, ValueError):
            previous = {}
    queued_this_run = int(details.get("queued", 0) or 0)
    queued_today = int(previous.get("queued_today", 0) or 0)
    if status == "completed":
        queued_today += queued_this_run
    payload = {
        "kind": kind,
        "status": status,
        "business_date": business_date,
        "updated_at": now.isoformat(),
        "queued_today": queued_today,
        **details,
    }
    await redis.set(
        collection_status_key(kind),
        json.dumps(payload, ensure_ascii=False),
        ex=_STATUS_TTL_SECONDS,
    )


async def collect_investoday_news_job(ctx: dict[str, Any]) -> dict[str, object]:
    """Fetch one bounded provider page and enqueue only coverage-matched new items."""

    conf = Settings()
    redis = ctx.get("redis")
    if not conf.investoday_news_enabled or not conf.investoday_api_key:
        result: dict[str, object] = {"ok": True, "status": "disabled", "queued": 0}
        await _write_collection_status(redis, kind="news", conf=conf, status="disabled", queued=0)
        return result
    await _write_collection_status(redis, kind="news", conf=conf, status="running")
    client = InvestodayNewsClient(
        api_key=conf.investoday_api_key.get_secret_value(),
        base_url=conf.investoday_news_base_url,
    )
    securities = _covered_securities(conf)
    targeted: list[tuple[InvestodayNews, str]] = []
    try:
        for security in securities:
            if code := _stock_code(security):
                targeted.extend(
                    (item, str(security.security_id))
                    for item in await client.fetch_latest(
                        page_size=conf.investoday_news_page_size, stock_code=code
                    )
                    if _item_mentions_security(item, security)
                )
    except InvestodayError as exc:
        result = {"ok": False, "status": "provider_error", "reason": str(exc), "queued": 0}
        await _write_collection_status(redis, kind="news", conf=conf, status="failed", queued=0)
        return result
    try:
        result = await _enqueue_targeted_items(
            items=targeted,
            kind="news",
            redis=redis,
            conf=conf,
            max_items=conf.investoday_news_max_items_per_run,
        )
    except Exception:
        await _write_collection_status(redis, kind="news", conf=conf, status="failed", queued=0)
        raise
    await _write_collection_status(
        redis,
        kind="news",
        conf=conf,
        status="completed" if result.get("ok") else "failed",
        fetched=result.get("fetched", 0),
        queued=result.get("queued", 0),
        skipped_seen=result.get("skipped_seen", 0),
    )
    return result


async def collect_investoday_reports_job(ctx: dict[str, Any]) -> dict[str, object]:
    """Daily, stock-code-targeted research-report collection."""

    conf = Settings()
    redis = ctx.get("redis")
    if not conf.investoday_reports_enabled or not conf.investoday_api_key:
        result: dict[str, object] = {"ok": True, "status": "disabled", "queued": 0}
        await _write_collection_status(redis, kind="report", conf=conf, status="disabled", queued=0)
        return result
    await _write_collection_status(redis, kind="report", conf=conf, status="running")
    client = InvestodayNewsClient(
        api_key=conf.investoday_api_key.get_secret_value(), base_url=conf.investoday_news_base_url
    )
    securities = _covered_securities(conf)
    targeted: list[tuple[InvestodayReport, str]] = []
    try:
        for security in securities:
            if code := _stock_code(security):
                targeted.extend(
                    (item, str(security.security_id))
                    for item in await client.fetch_reports(
                        stock_code=code, page_size=conf.investoday_reports_page_size
                    )
                    if _item_mentions_security(item, security)
                )
    except InvestodayError as exc:
        result = {"ok": False, "status": "provider_error", "reason": str(exc), "queued": 0}
        await _write_collection_status(redis, kind="report", conf=conf, status="failed", queued=0)
        return result
    try:
        result = await _enqueue_targeted_items(
            items=targeted,
            kind="report",
            redis=redis,
            conf=conf,
            max_items=conf.investoday_reports_max_items_per_run,
        )
    except Exception:
        await _write_collection_status(redis, kind="report", conf=conf, status="failed", queued=0)
        raise
    await _write_collection_status(
        redis,
        kind="report",
        conf=conf,
        status="completed" if result.get("ok") else "failed",
        fetched=result.get("fetched", 0),
        queued=result.get("queued", 0),
        skipped_seen=result.get("skipped_seen", 0),
    )
    return result


async def _enqueue_targeted_items(
    *, items: list[tuple[Any, str]], kind: str, redis: Any, conf: Settings, max_items: int
) -> dict[str, object]:
    if redis is None:
        return {
            "ok": False,
            "status": "queue_unavailable",
            "reason": "ARQ Redis 未连接",
            "queued": 0,
        }
    queued = skipped_seen = 0
    for item, security_id in items[:max_items]:
        key = f"copilot:collection:investoday:{kind}:{item.item_id}"
        if not await redis.set(key, "pending", ex=_DEDUPE_TTL_SECONDS, nx=True):
            skipped_seen += 1
            continue
        try:
            await _archive_and_enqueue(
                item=item, kind=kind, security_id=security_id, redis=redis, conf=conf
            )
            await redis.set(key, "queued", ex=_DEDUPE_TTL_SECONDS)
            queued += 1
        except Exception:
            await redis.delete(key)
            raise
    return {
        "ok": True,
        "status": "completed",
        "fetched": len(items),
        "queued": queued,
        "skipped_seen": skipped_seen,
    }


def _covered_securities(conf: Settings) -> list[Any]:
    """Only query companies that have a current investment logic.

    A company master entry is not by itself a research-coverage decision. This
    keeps unrelated supplier material out of the model pipeline and ensures
    every collected item has a logic against which it can be assessed.
    """

    with uow_scope() as uow:
        theses, _ = uow.thesis.search(ThesisQuery(limit=1_000, include_snapshots=True))
        covered_ids = {item.security_id for item in theses}
        excluded_ids = {
            security_id.strip()
            for security_id in conf.investoday_excluded_security_ids.split(",")
            if security_id.strip()
        }
        return [
            security
            for security in uow.securities.search(None, limit=1_000)
            if str(security.security_id) in covered_ids and str(security.security_id) not in excluded_ids
        ]


async def _archive_and_enqueue(
    *, item: Any, kind: str, security_id: str, redis: Any, conf: Settings
) -> None:
    document_id = f"DOC-{uuid4().hex}"
    job_id = f"document-{document_id}"
    filename = f"investoday-{kind}-{item.item_id}.txt"
    path = (conf.storage_dir / "uploads" / filename).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, item.as_text(), encoding="utf-8")
    try:
        object_store = S3ObjectStore(conf)
        await asyncio.to_thread(object_store.ensure_bucket)
        with uow_scope() as uow:
            source_id = _ensure_investoday_source(uow, kind=kind)
            revision, duplicate = await asyncio.to_thread(
                asset_service.archive_upload,
                uow,
                path=path,
                document_id=document_id,
                source_filename=filename,
                media_type="text/plain",
                published_at=item.published_at,
                actor=_SYSTEM_ACTOR,
                object_store=object_store,
                source_id=source_id,
                source_url=f"https://data-api.investoday.net/data/{'news' if kind == 'news' else 'report/research'}?id={item.item_id}",
                authorization_status="已配置供应商 API 授权",
            )
            if duplicate:
                document_id = revision.canonical_document_id or revision.document_id
                job_id = f"document-{document_id}-r-{uuid4().hex[:12]}"
            run = asset_service.create_run(uow, revision_id=revision.revision_id, settings=conf)
            ingestion_service.create_job(
                uow,
                job_id=job_id,
                document_id=document_id,
                path=None,
                source_filename=filename,
                actor=_SYSTEM_ACTOR,
                published_at=item.published_at,
                security_id=security_id,
                thesis_id=None,
                view=f"今日投资自动采集：{'新闻' if kind == 'news' else '研报'}",
                revision_id=revision.revision_id,
                object_key=revision.object_key,
                object_version_id=revision.object_version_id,
                upload_content_hash=revision.content_hash,
                ingestion_run_id=run.run_id,
            )
        await enqueue_document(
            redis,
            document_id=document_id,
            path="",
            actor=_SYSTEM_ACTOR,
            published_at=item.published_at,
            security_id=security_id,
            view=f"今日投资自动采集：{'新闻' if kind == 'news' else '研报'}",
            revision_id=revision.revision_id,
            object_key=revision.object_key,
            object_version_id=revision.object_version_id,
            upload_content_hash=revision.content_hash,
            ingestion_run_id=run.run_id,
            source_filename=filename,
            job_id=job_id,
        )
    finally:
        path.unlink(missing_ok=True)


def _match_security(item: InvestodayNews, securities: list[Any]) -> str | None:
    """Return one unambiguous covered security; avoid speculative multi-company routing."""

    text = f"{item.title}\n{item.summary}\n{item.key_points}".lower()
    matches: list[str] = []
    for security in securities:
        terms = [security.name, security.ticker or "", *security.aliases]
        if any(_term_occurs(text, term.lower()) for term in terms if term):
            matches.append(str(security.security_id))
    return matches[0] if len(matches) == 1 else None


def _item_mentions_security(item: Any, security: Any) -> bool:
    """Do not trust a supplier's stock-code filter as an entity assertion.

    The provider can return broad-market articles for a stock-code request.
    Before creating an ingestion job, require a company name, alias, ticker or
    bare code to occur in the source text.  Wider industry inference belongs
    in a future, separately reviewed classifier — it must not create a
    company-level candidate relation by itself.
    """

    text = "\n".join(
        str(getattr(item, field, "") or "")
        for field in ("title", "summary", "key_points", "content", "keyword")
    ).lower()
    terms = [security.name, security.ticker or "", str(security.security_id), *security.aliases]
    return any(_term_occurs(text, str(term).lower()) for term in terms if str(term).strip())


def _term_occurs(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9.]+", term):
        return re.search(rf"(?<![a-z0-9.]){re.escape(term)}(?![a-z0-9.])", text) is not None
    return term in text


def _stock_code(security: Any) -> str | None:
    """Provider accepts the bare exchange code for both A and Hong Kong shares."""

    raw = str(security.ticker or security.security_id or "").strip().upper()
    return raw.split(".", maxsplit=1)[0] or None


def _ensure_investoday_source(uow: Any, *, kind: str) -> str:
    """Create the fixed licensed-provider lineage record exactly once."""

    source_id = f"SRC-INVESTODAY-{'NEWS' if kind == 'news' else 'REPORT'}"
    if uow.assets.get_source(source_id) is None:
        uow.assets.add_source(
            SourceRecord(
                source_id=source_id,
                name=f"今日投资{'新闻' if kind == 'news' else '研究报告'} API",
                source_type="商业资讯接口",
                authorization_status="已配置供应商 API 授权",
                base_url="https://data-api.investoday.net/data",
                license_note="仅用于内部投研线索与溯源；不得将原始内容对外再分发。",
            )
        )
    return source_id
