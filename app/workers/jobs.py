"""ARQ job entry points for durable asynchronous document processing."""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from arq import Retry

from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.ai.runtime import InvestmentResearchAgent
from app.core.config import Settings
from app.core.domain import DocumentSecurityRelationRecord, EventRecord
from app.core.enums import AiStatus
from app.ingest.events import ExtractedEvent
from app.ingest.facts import extract_key_facts
from app.ingest.segmentation import Segment, event_fingerprint
from app.services import assets as asset_service
from app.services import document as document_service
from app.services import ingestion as ingestion_service
from app.services.ai_runtime import SqlRuntimeRecorder
from app.services.object_store import S3ObjectStore
from app.services.permission import Actor
from app.services.review import create_task
from app.services.uow import uow_scope
from app.workers.change_chain import ChangeResult, process_events_async
from app.workers.document_chain import DocumentResult, process_document

# Compatibility seam used by existing worker tests and integrations.
process_events = process_events_async


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
    """第一阶段：解析并落库；真实 worker 随后投递独立 AI 任务。"""
    document_id = str(payload["document_id"])
    job_id = str(payload.get("job_id") or f"document-{document_id}")
    job_try = int(ctx.get("job_try", payload.get("attempt_count", 1)))
    attempt_count = int(payload.get("attempt_count", 1)) + job_try - 1
    try:
        if payload.get("job_id"):
            await _wait_until_job_is_visible(job_id)
        with uow_scope() as uow:
            ingestion_service.mark_running(uow, job_id, attempt_count=attempt_count)
            ingestion_service.mark_progress(
                uow, job_id, stage="reusing_parsed" if payload.get("analysis_only") else "parsing"
            )
            if payload.get("ingestion_run_id"):
                asset_service.mark_run_running(uow, str(payload["ingestion_run_id"]))
        split_stage = ctx.get("redis") is not None and not payload.get("analysis_only")
        result = await _process_document(ctx, payload | {"parse_only": split_stage})
        if split_stage and result.get("ok") and result.get("requires_analysis"):
            with uow_scope() as uow:
                ingestion_service.mark_progress(
                    uow,
                    job_id,
                    stage="analysis_queued",
                    detail={key: value for key, value in result.items() if key != "stage"},
                )
            await ctx["redis"].enqueue_job(
                "analyze_document_job",
                payload | {"analysis_only": True},
                _job_id=f"{job_id}:analysis",
            )
            return result | {"stage": "analysis_queued"}
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


async def analyze_document_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """第二阶段：复用已落库分段/事件运行 AI，不再读取原 PDF。"""
    document_id = str(payload["document_id"])
    job_id = str(payload.get("job_id") or f"document-{document_id}")
    actor = _actor(payload)
    try:
        with uow_scope() as uow:
            ingestion_service.mark_progress(uow, job_id, stage="analysis_started")
        result = await _process_document(ctx, payload | {"analysis_only": True})
    except Exception as exc:
        result = {
            "ok": False,
            "document_id": document_id,
            "reason": str(exc),
            "stage": "analysis_failed",
            "parsed": True,
            "manual_review": True,
            "dead_letter": True,
        }
        _create_failure_review(
            thesis_id=str(payload["thesis_id"]) if payload.get("thesis_id") else None,
            actor=actor,
            document_id=document_id,
            reason=str(exc),
        )
    with uow_scope() as uow:
        previous = uow.processing_jobs.get(job_id)
        if previous is not None and previous.result:
            preserved = {
                key: previous.result[key]
                for key in ("segment_count", "fact_count", "content_hash", "parser_version")
                if key in previous.result
            }
            result = preserved | result
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


async def _run_change_chain(
    *,
    gateway: Gateway,
    events: list[ExtractedEvent],
    security_id: str,
    actor: Actor,
    settings: Settings,
    document_id: str,
    document_title: str,
    source_visibility_label: str,
    source_url: str | None,
) -> ChangeResult:
    """异步完成模型关系分析；远程超时会取消底层 HTTP 请求。"""
    with uow_scope() as uow:
        runtime = InvestmentResearchAgent.build(
            gateway,
            recorder=SqlRuntimeRecorder(),
        )
        result = process_events(
            uow,
            runtime,
            events=events,
            security_id=security_id,
            actor=actor,
            thresholds=settings.rules,
            current_event_segments=uow.documents.list_segments(document_id),
            document_id=document_id,
            document_title=document_title,
            source_visibility_label=source_visibility_label,
            source_url=source_url,
            rag_settings=settings,
        )
        return await result if inspect.isawaitable(result) else result


async def _process_document(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    settings = Settings()
    document_id = str(payload["document_id"])
    job_id = str(payload.get("job_id") or f"document-{document_id}")
    downloaded_from_object = False
    analysis_only = bool(payload.get("analysis_only"))
    actor = _actor(payload)
    if analysis_only:
        with uow_scope() as uow:
            persisted = uow.documents.get(document_id)
            cached_segments = uow.documents.list_segments(document_id)
        if persisted is None or not cached_segments:
            raise ValueError("已入库资料或分段不存在，无法只重新分析")
        path = Path(str(payload.get("source_filename") or document_id))
        result = DocumentResult(
            document_id=document_id,
            ok=True,
            segments=[
                Segment(
                    document_id=item.document_id,
                    locator=item.locator,
                    ordinal=item.ordinal,
                    content=item.content,
                    page=item.page,
                    content_kind=item.content_kind,
                    extraction_method=item.extraction_method,
                    table_index=item.table_index,
                    row_index=item.row_index,
                    cell_range=item.cell_range,
                    confidence=item.confidence,
                )
                for item in cached_segments
            ],
            title=persisted.title,
            doc_type=persisted.doc_type,
            content_hash=persisted.content_hash,
            parser_version=persisted.parser_version,
            published_at=persisted.published_at,
        )
    elif payload.get("object_key"):
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
    if not analysis_only:
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
    if not analysis_only:
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

    assert persisted is not None

    with uow_scope() as uow:
        ingestion_service.mark_progress(
            uow,
            job_id,
            stage="indexed",
            detail={"segment_count": len(result.segments), "fact_count": len(facts)},
        )

    duplicate_document = False if analysis_only else persisted.document_id != document_id
    security_id = str(payload["security_id"]) if payload.get("security_id") else None
    assignment_replay = bool(
        "-a-" in job_id
        and security_id
        and duplicate_document
        and persisted.security_id == security_id
    )
    event_count = candidate_count = duplicate_event_count = 0
    matched_theses: list[str] = []
    deferred_count = 0
    extraction_mode = "none"
    retrieval_mode = "baseline"
    graph_snapshot_id: str | None = None
    recall_rankings: list[dict[str, object]] = []
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
    if payload.get("parse_only"):
        if downloaded_from_object or (
            duplicate_document and path.resolve() != Path(persisted.raw_path or "").resolve()
        ):
            path.unlink(missing_ok=True)
        return {
            "ok": True,
            "parsed": True,
            "stage": "indexed",
            "document_id": document_id,
            "persisted_document_id": persisted.document_id,
            "duplicate": duplicate_document,
            "segment_count": len(result.segments),
            "fact_count": len(facts),
            "content_hash": result.content_hash,
            "parser_version": result.parser_version,
            "requires_analysis": bool(
                security_id and (not duplicate_document or assignment_replay)
            ),
            "security_candidates": security_candidates,
            "draft_created": False,
        }
    if security_id and (not duplicate_document or assignment_replay):
        try:
            with uow_scope() as uow:
                ingestion_service.mark_progress(uow, job_id, stage="extracting_events")
            gateway = Gateway.build(settings)
            model_events: list[dict[str, Any]] = []
            source_segments = [(segment.locator, segment.content) for segment in result.segments]
            for batch in _segment_batches(source_segments):
                async with asyncio.timeout(settings.llm_analysis_timeout_seconds):
                    if hasattr(gateway, "extract_events_async"):
                        extraction = await gateway.extract_events_async(
                            document_id=persisted.document_id,
                            segments=batch,
                            disclosure_time=persisted.published_at.isoformat(),
                        )
                    else:
                        extraction = gateway.extract_events(
                            document_id=persisted.document_id,
                            segments=batch,
                            disclosure_time=persisted.published_at.isoformat(),
                        )
                if extraction.ai_status is AiStatus.PARSE_FAILED:
                    raise ModelUnavailable("结构化事件抽取输出不符合契约", retryable=False)
                model_events.extend(extraction.payload.get("events", []))
            extracted = _events_from_model(
                persisted.document_id,
                security_id,
                persisted.published_at,
                {"events": model_events},
            )
            extraction_mode = "model" if settings.llm_provider == "http" else "configured_local"
            with uow_scope() as uow:
                new_events: list[ExtractedEvent] = []
                persisted_events: list[EventRecord] = []
                seen_event_ids: set[str] = set()
                for event in extracted:
                    if event.event_id in seen_event_ids:
                        # 同一批模型输出可能重复返回同一个稳定编号；只保留一次。
                        duplicate_event_count += 1
                        continue
                    seen_event_ids.add(event.event_id)
                    existing_by_id = uow.events.get(event.event_id)
                    if existing_by_id is not None:
                        # 模型重放可能改变摘要，从而改变 fingerprint，但同一文档的
                        # 稳定事件编号仍必须复用，不能再次插入主键。
                        duplicate_event_count += 1
                        new_events.append(replace(event, event_id=existing_by_id.event_id))
                        continue
                    existing = uow.events.find_by_fingerprint(event.fingerprint)
                    if existing is not None:
                        same_document = event.document_id in existing.source_document_ids
                        sources = sorted({*existing.source_document_ids, event.document_id})
                        if sources != existing.source_document_ids:
                            uow.events.update(replace(existing, source_document_ids=sources))
                        duplicate_event_count += 1
                        # 同一文档的分析重放必须复用既有事件继续做假设关联；
                        # 其他文档的重复事实只合并来源，避免重复候选证据。
                        if same_document:
                            new_events.append(replace(event, event_id=existing.event_id))
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

            event_count = len(new_events)
            with uow_scope() as uow:
                ingestion_service.mark_progress(
                    uow,
                    job_id,
                    stage="matching_hypotheses",
                    detail={"event_count": event_count},
                )
            async with asyncio.timeout(settings.llm_analysis_timeout_seconds):
                chain = await _run_change_chain(
                    gateway=gateway,
                    events=new_events,
                    security_id=security_id,
                    actor=actor,
                    settings=settings,
                    document_id=persisted.document_id,
                    document_title=persisted.title or path.name,
                    source_visibility_label=persisted.visibility_label,
                    source_url=None,
                )
            event_count = len(new_events)
            candidate_count = len(chain.candidates)
            matched_theses = chain.matched_theses
            deferred_count = len(chain.deferred)
            retrieval_mode = chain.retrieval_mode
            graph_snapshot_id = chain.graph_snapshot_id
            recall_rankings = [trace.to_dict() for trace in chain.recall_traces]
            with uow_scope() as uow:
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
        except (ModelUnavailable, TimeoutError) as exc:
            reason = (
                f"AI 分析超过 {settings.llm_analysis_timeout_seconds:g} 秒，已停止；可重新分析"
                if isinstance(exc, TimeoutError)
                else str(exc)
            )
            with uow_scope() as uow:
                ingestion_service.mark_progress(
                    uow,
                    job_id,
                    stage="analysis_timeout"
                    if isinstance(exc, TimeoutError)
                    else "analysis_failed",
                )
            _create_failure_review(
                thesis_id=str(payload["thesis_id"]) if payload.get("thesis_id") else None,
                actor=actor,
                document_id=document_id,
                reason=reason,
            )
            if downloaded_from_object:
                path.unlink(missing_ok=True)
            return {
                "ok": False,
                "document_id": document_id,
                "reason": reason,
                "stage": "analysis_timeout" if isinstance(exc, TimeoutError) else "analysis_failed",
                "parsed": True,
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
        "parsed": True,
        "stage": "completed",
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
        "retrieval_mode": retrieval_mode,
        "graph_snapshot_id": graph_snapshot_id,
        "recall_rankings": recall_rankings,
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
