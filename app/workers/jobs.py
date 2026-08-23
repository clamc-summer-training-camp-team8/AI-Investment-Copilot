"""ARQ job entry points for durable asynchronous document processing."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from arq import Retry

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.providers.local import LocalProvider
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings
from app.core.domain import DocumentSecurityRelationRecord, EventRecord
from app.core.enums import AiStatus
from app.ingest.events import ExtractedEvent, extract_events_from_segments
from app.ingest.facts import extract_key_facts
from app.ingest.segmentation import event_fingerprint
from app.services import assets as asset_service
from app.services import document as document_service
from app.services import ingestion as ingestion_service
from app.services.ai_runtime import SqlRuntimeRecorder
from app.services.object_store import S3ObjectStore
from app.services.permission import Actor
from app.services.review import create_task
from app.services.uow import uow_scope
from app.workers.change_chain import process_events
from app.workers.document_chain import process_document


def _published_at(raw: str | None) -> datetime | None:
    return None if raw is None else datetime.fromisoformat(raw)


def _safe_upload_path(path: str, settings: Settings) -> Path:
    resolved = Path(path).resolve()
    root = (settings.storage_dir / "uploads").resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("任务文件不在受控上传目录")
    return resolved


def _create_failure_review(
    *,
    thesis_id: str | None,
    actor: Actor,
    document_id: str,
    reason: str,
) -> None:
    if not thesis_id:
        return
    with uow_scope() as uow:
        create_task(
            uow,
            thesis_id=thesis_id,
            trigger="处理失败",
            priority="高",
            assignee=actor.user_id,
            actor=actor,
            detail={"document_id": document_id, "reason": reason},
        )


async def process_document_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """解析资料，并在已建档证券上运行变化处理链。"""
    document_id = str(payload["document_id"])
    job_id = str(payload.get("job_id") or f"document-{document_id}")
    job_try = int(ctx.get("job_try", payload.get("attempt_count", 1)))
    attempt_count = int(payload.get("attempt_count", 1)) + job_try - 1
    try:
        if payload.get("job_id"):
            await _wait_until_job_is_visible(job_id)
        with uow_scope() as uow:
            ingestion_service.mark_running(uow, job_id, attempt_count=attempt_count)
            if payload.get("ingestion_run_id"):
                asset_service.mark_run_running(uow, str(payload["ingestion_run_id"]))
        result = await _process_document(ctx, payload)
        with uow_scope() as uow:
            ingestion_service.mark_complete(
                uow,
                job_id,
                result=result,
                success=bool(result.get("ok")),
                dead_letter=bool(result.get("dead_letter")),
            )
            if payload.get("ingestion_run_id"):
                asset_service.complete_run(
                    uow,
                    str(payload["ingestion_run_id"]),
                    success=bool(result.get("ok")),
                    result=result,
                )
        return result
    except Retry:
        _remove_downloaded_spool(payload, job_id)
        with uow_scope() as uow:
            ingestion_service.mark_retrying(
                uow, job_id, reason="等待自动重试", attempt_count=attempt_count
            )
        raise
    except Exception as exc:
        _remove_downloaded_spool(payload, job_id)
        max_tries = int(ctx.get("max_tries", payload.get("max_attempts", 3)))
        if job_try < max_tries:
            with uow_scope() as uow:
                ingestion_service.mark_retrying(
                    uow, job_id, reason=str(exc), attempt_count=attempt_count
                )
            raise Retry(defer=min(5 * (2 ** (job_try - 1)), 60)) from exc
        actor = _actor(payload)
        failure: dict[str, object] = {
            "ok": False,
            "document_id": document_id,
            "reason": str(exc),
            "manual_review": True,
            "dead_letter": True,
        }
        with uow_scope() as uow:
            ingestion_service.mark_complete(
                uow, job_id, result=failure, success=False, dead_letter=True
            )
            if payload.get("ingestion_run_id"):
                asset_service.complete_run(
                    uow,
                    str(payload["ingestion_run_id"]),
                    success=False,
                    result=failure,
                )
            ingestion_service.create_review(
                uow,
                review_type="processing_failure",
                document_id=document_id,
                job_id=job_id,
                reason=str(exc),
                actor=actor,
                payload={"dead_letter": True, "attempt": job_try},
            )
        return failure


async def _wait_until_job_is_visible(job_id: str, *, timeout_seconds: float = 2.0) -> None:
    """Bridge the short interval between Redis enqueue and API transaction commit."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        with uow_scope() as uow:
            if uow.processing_jobs.get(job_id) is not None:
                return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"processing job is not committed yet: {job_id}")
        await asyncio.sleep(0.05)


def _actor(payload: dict[str, Any]) -> Actor:
    return Actor(
        user_id=str(payload["actor_id"]),
        teams=frozenset(str(item) for item in payload.get("actor_teams", [])),
    )


async def _process_document(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    settings = Settings()
    document_id = str(payload["document_id"])
    job_id = str(payload.get("job_id") or f"document-{document_id}")
    downloaded_from_object = False
    if payload.get("object_key"):
        suffix = Path(str(payload.get("source_filename") or "source.bin")).suffix.lower()
        path = (settings.storage_dir / "processing" / f"{job_id}{suffix}").resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        await asyncio.to_thread(
            S3ObjectStore(settings).download,
            object_key=str(payload["object_key"]),
            destination=path,
            version_id=(
                str(payload["object_version_id"]) if payload.get("object_version_id") else None
            ),
        )
        downloaded_from_object = True
    else:
        path = _safe_upload_path(str(payload["path"]), settings)
    actor = _actor(payload)
    result = await asyncio.to_thread(
        process_document,
        document_id=document_id,
        path=path,
        published_at=_published_at(payload.get("published_at")),
    )
    if not result.ok:
        reason = result.failure_reason or "文档处理失败"
        _create_failure_review(
            thesis_id=payload.get("thesis_id"),
            actor=actor,
            document_id=document_id,
            reason=reason,
        )
        with uow_scope() as uow:
            ingestion_service.create_review(
                uow,
                review_type="processing_failure",
                document_id=document_id,
                job_id=job_id,
                reason=reason,
                actor=actor,
            )
        if downloaded_from_object:
            path.unlink(missing_ok=True)
        return {
            "ok": False,
            "document_id": document_id,
            "reason": reason,
            "manual_review": True,
            "dead_letter": True,
        }

    facts = extract_key_facts(result.segments)
    with uow_scope() as uow:
        persisted = document_service.persist_processed(
            uow,
            document_id=result.document_id,
            title=result.title,
            doc_type=result.doc_type,
            published_at=result.published_at,
            content_hash=result.content_hash,
            parser_version=result.parser_version,
            segments=result.segments,
            path=path,
            actor=actor,
            security_id=str(payload["security_id"]) if payload.get("security_id") else None,
            facts=facts,
            raw_location=(
                f"s3://{settings.object_store_bucket}/{payload['object_key']}"
                if payload.get("object_key")
                else None
            ),
        )
        if payload.get("revision_id"):
            revision = uow.assets.get_revision(str(payload["revision_id"]))
            if revision:
                uow.assets.update_revision(
                    replace(revision, canonical_document_id=persisted.document_id)
                )
        if security_id := (str(payload["security_id"]) if payload.get("security_id") else None):
            uow.assets.add_document_security(
                DocumentSecurityRelationRecord(
                    document_id=persisted.document_id,
                    security_id=security_id,
                    created_by=actor.user_id,
                )
            )
        if payload.get("ingestion_run_id"):
            uow.assets.remove_document_from_index(persisted.document_id)
            asset_service.persist_artifacts(
                uow,
                run_id=str(payload["ingestion_run_id"]),
                segments=result.segments,
                facts=facts,
                document_id=persisted.document_id,
                visibility_label=persisted.visibility_label,
            )

    duplicate_document = persisted.document_id != document_id
    security_id = str(payload["security_id"]) if payload.get("security_id") else None
    assignment_replay = bool(
        "-assignment-" in job_id
        and security_id
        and duplicate_document
        and persisted.security_id == security_id
    )
    event_count = candidate_count = duplicate_event_count = 0
    matched_theses: list[str] = []
    deferred_count = 0
    extraction_mode = "none"
    security_candidates: list[dict[str, object]] = []
    if not security_id and not duplicate_document:
        with uow_scope() as uow:
            security_candidates = ingestion_service.suggest_securities(
                uow,
                title=persisted.title,
                segments=[(segment.locator, segment.content) for segment in result.segments],
            )
            ingestion_service.create_review(
                uow,
                review_type="security_assignment",
                document_id=persisted.document_id,
                job_id=job_id,
                reason="资料尚未归属证券，请确认候选后再进入雷达链",
                actor=actor,
                security_candidates=security_candidates,
            )
    if security_id and (not duplicate_document or assignment_replay):
        try:
            try:
                gateway = Gateway.build(settings)
                model_events: list[dict[str, Any]] = []
                source_segments = [
                    (segment.locator, segment.content) for segment in result.segments
                ]
                for batch in _segment_batches(source_segments):
                    extraction = gateway.extract_events(
                        document_id=persisted.document_id,
                        segments=batch,
                        disclosure_time=persisted.published_at.isoformat(),
                    )
                    if extraction.ai_status is AiStatus.PARSE_FAILED:
                        raise ValueError("结构化事件抽取输出不符合契约")
                    model_events.extend(extraction.payload.get("events", []))
                extracted = _events_from_model(
                    persisted.document_id,
                    security_id,
                    persisted.published_at,
                    {"events": model_events},
                )
                extraction_mode = "model" if settings.llm_provider == "http" else "rule_fallback"
            except (AttributeError, ModelUnavailable, ValueError):
                gateway = Gateway(settings=settings, provider=LocalProvider(settings))
                extracted = extract_events_from_segments(
                    persisted.document_id,
                    security_id,
                    [(segment.locator, segment.content) for segment in result.segments],
                    disclosure_time=persisted.published_at,
                )
                extraction_mode = "rule_fallback"
            with uow_scope() as uow:
                new_events: list[ExtractedEvent] = []
                persisted_events: list[EventRecord] = []
                for event in extracted:
                    existing = uow.events.find_by_fingerprint(event.fingerprint)
                    if existing is not None:
                        sources = sorted({*existing.source_document_ids, event.document_id})
                        if sources != existing.source_document_ids:
                            uow.events.update(replace(existing, source_document_ids=sources))
                        duplicate_event_count += 1
                        continue
                    persisted_event = EventRecord(
                        event_id=event.event_id,
                        document_id=event.document_id,
                        security_id=event.security_id,
                        event_type=event.event_type,
                        summary=event.summary,
                        occurred_on=event.occurred_on,
                        disclosure_time=event.disclosure_time,
                        fingerprint=event.fingerprint,
                        source_document_ids=[event.document_id],
                    )
                    uow.events.add(persisted_event)
                    persisted_events.append(persisted_event)
                    new_events.append(event)
                    if event.ai_confidence is not None and event.ai_confidence < Decimal(
                        str(settings.rules.low_confidence_cutoff)
                    ):
                        ingestion_service.create_review(
                            uow,
                            review_type="low_confidence",
                            document_id=persisted.document_id,
                            job_id=job_id,
                            event_id=event.event_id,
                            reason=(
                                f"事件抽取置信度 {event.ai_confidence} 低于阈值 "
                                f"{settings.rules.low_confidence_cutoff}"
                            ),
                            actor=actor,
                        )

                if payload.get("ingestion_run_id"):
                    asset_service.persist_event_artifacts(
                        uow,
                        run_id=str(payload["ingestion_run_id"]),
                        events=persisted_events,
                    )

                runtime = InvestmentResearchAgent.build(
                    gateway,
                    recorder=SqlRuntimeRecorder(),
                )
                chain = process_events(
                    uow,
                    runtime,
                    events=new_events,
                    security_id=security_id,
                    actor=actor,
                    thresholds=settings.rules,
                    current_event_segments=uow.documents.list_segments(persisted.document_id),
                    document_id=persisted.document_id,
                    document_title=persisted.title or path.name,
                    source_visibility_label=persisted.visibility_label,
                    rag_settings=settings,
                )
                event_count = len(new_events)
                candidate_count = len(chain.candidates)
                matched_theses = chain.matched_theses
                deferred_count = len(chain.deferred)
                if new_events and not chain.matched_theses:
                    for event in new_events:
                        ingestion_service.create_review(
                            uow,
                            review_type="hypothesis_matching",
                            document_id=persisted.document_id,
                            job_id=job_id,
                            event_id=event.event_id,
                            reason="该证券没有可召回的已发布逻辑，或事件无法匹配具体假设",
                            actor=actor,
                        )
                for event_id, reason in chain.deferred:
                    review_type = "low_confidence" if "低置信" in reason else "hypothesis_matching"
                    ingestion_service.create_review(
                        uow,
                        review_type=review_type,
                        document_id=persisted.document_id,
                        job_id=job_id,
                        event_id=event_id,
                        reason=reason,
                        actor=actor,
                    )
        except ModelUnavailable as exc:
            job_try = int(ctx.get("job_try", 1))
            max_tries = int(ctx.get("max_tries", 3))
            if exc.retryable and job_try < max_tries:
                raise Retry(defer=min(5 * (2 ** (job_try - 1)), 60)) from exc
            _create_failure_review(
                thesis_id=str(payload["thesis_id"]) if payload.get("thesis_id") else None,
                actor=actor,
                document_id=document_id,
                reason=str(exc),
            )
            if downloaded_from_object:
                path.unlink(missing_ok=True)
            return {
                "ok": False,
                "document_id": document_id,
                "reason": str(exc),
                "manual_review": True,
                "dead_letter": True,
            }

    if downloaded_from_object:
        path.unlink(missing_ok=True)
    elif duplicate_document and path.resolve() != Path(persisted.raw_path or "").resolve():
        # 数据库已引用旧原件，新上传副本没有业务引用，立即清理避免重复堆积。
        path.unlink(missing_ok=True)

    return {
        "ok": True,
        "document_id": document_id,
        "persisted_document_id": persisted.document_id,
        "duplicate": duplicate_document,
        "segment_count": len(result.segments),
        "fact_count": len(facts),
        "content_hash": result.content_hash,
        "parser_version": result.parser_version,
        "event_count": event_count,
        "duplicate_event_count": duplicate_event_count,
        "matched_thesis_count": len(matched_theses),
        "matched_thesis_ids": matched_theses,
        "candidate_evidence_count": candidate_count,
        "deferred_event_count": deferred_count,
        "event_extraction_mode": extraction_mode,
        "security_candidates": security_candidates,
        # 兼容旧客户端字段：上传资料现在不再错误地新建逻辑草稿。
        "draft_created": False,
    }


def _segment_batches(
    segments: list[tuple[str, str]], *, max_items: int = 25, max_chars: int = 24_000
) -> list[list[tuple[str, str]]]:
    """Bound each model request while preserving every segment's exact locator."""

    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_chars = 0
    for segment in segments:
        segment_chars = len(segment[0]) + len(segment[1]) + 3
        if current and (len(current) >= max_items or current_chars + segment_chars > max_chars):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(segment)
        current_chars += segment_chars
    if current:
        batches.append(current)
    return batches or [[]]


def _events_from_model(
    document_id: str,
    security_id: str,
    disclosure_time: datetime,
    payload: dict[str, Any],
) -> list[ExtractedEvent]:
    events: list[ExtractedEvent] = []
    for index, item in enumerate(payload.get("events", []), start=1):
        if not isinstance(item, dict):
            continue
        summary = str(item["fact"]).strip()
        occurred = item.get("occurred_on")
        locator = str(item["evidence_locator"])
        events.append(
            ExtractedEvent(
                event_id=f"{document_id}-EVT-{index}",
                document_id=document_id,
                security_id=security_id,
                event_type=str(item["event_type"]),
                summary=summary,
                disclosure_time=disclosure_time,
                occurred_on=datetime.fromisoformat(str(occurred)).date() if occurred else None,
                fingerprint=event_fingerprint(security_id, summary),
                evidence_locator=locator,
                ai_confidence=Decimal(str(item["confidence"])),
            )
        )
    return events


async def cleanup_uploads_job(ctx: dict[str, Any]) -> dict[str, int]:
    """清理重复副本、过期失败文件和无任务孤儿；成功入库的原件始终保留。"""
    settings = Settings()
    root = (settings.storage_dir / "uploads").resolve()
    if not root.exists():
        return {"deleted": 0, "kept": 0}
    now_utc = datetime.now(UTC)
    deleted = kept = 0
    with uow_scope() as uow:
        for path in root.iterdir():
            if not path.is_file():
                continue
            document_id = path.stem
            job = uow.processing_jobs.get_by_document(document_id)
            age = now_utc - datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if job is None:
                should_delete = age >= timedelta(days=settings.upload_retention_days)
            elif job.status in {"failed", "dead_letter"}:
                should_delete = age >= timedelta(days=settings.failed_upload_retention_days)
            else:
                should_delete = False
            if should_delete:
                path.unlink(missing_ok=True)
                deleted += 1
            else:
                kept += 1
    return {"deleted": deleted, "kept": kept}


def _remove_downloaded_spool(payload: dict[str, Any], job_id: str) -> None:
    if not payload.get("object_key"):
        return
    suffix = Path(str(payload.get("source_filename") or "source.bin")).suffix.lower()
    path = (Settings().storage_dir / "processing" / f"{job_id}{suffix}").resolve()
    path.unlink(missing_ok=True)


async def recover_stale_jobs(ctx: dict[str, Any]) -> dict[str, int]:
    """Worker/Redis 意外退出后，把长时间未完成的任务转成可见、可重放的死信。"""
    before = datetime.now(UTC) - timedelta(minutes=15)
    recovered = 0
    with uow_scope() as uow:
        for record in uow.processing_jobs.list_stale(
            before=before, statuses=("queued", "running", "retrying")
        ):
            result: dict[str, object] = {
                "ok": False,
                "document_id": record.document_id,
                "reason": "任务超过 15 分钟未完成，可能因 Worker 中断而遗留",
                "manual_review": True,
                "dead_letter": True,
            }
            ingestion_service.mark_complete(
                uow, record.job_id, result=result, success=False, dead_letter=True
            )
            ingestion_service.create_review(
                uow,
                review_type="processing_failure",
                document_id=record.document_id,
                job_id=record.job_id,
                reason=str(result["reason"]),
                actor=Actor(user_id=record.owner, teams=frozenset(record.actor_teams)),
                payload={"dead_letter": True, "recovered": True},
            )
            recovered += 1
    return {"recovered": recovered}
