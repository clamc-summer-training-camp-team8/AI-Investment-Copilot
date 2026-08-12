"""Research-asset lineage, inventories, reprocessing and thesis revision drafts."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from app.ai.embeddings import embed_text
from app.core.config import Settings
from app.core.domain import (
    AssetSearchHitRecord,
    DocumentRevisionRecord,
    EventRecord,
    HypothesisRecord,
    IngestionArtifactRecord,
    IngestionRunRecord,
    MetricMappingRecord,
    SegmentEmbeddingRecord,
    ThesisRevisionDraftRecord,
    UnitOfWork,
)
from app.core.enums import ExpectationDirection, Importance
from app.core.timeutil import now
from app.services import audit, version
from app.services.errors import HumanGateRequired, NotVisible, ValidationFailed
from app.services.object_store import ObjectStore
from app.services.permission import Actor


def archive_upload(
    uow: UnitOfWork,
    *,
    path: Path,
    document_id: str,
    source_filename: str,
    media_type: str | None,
    published_at,
    actor: Actor,
    object_store: ObjectStore,
) -> tuple[DocumentRevisionRecord, bool]:
    digest = _file_hash(path)
    existing = uow.assets.find_revision_by_hash(digest)
    if existing:
        path.unlink(missing_ok=True)
        return existing, True
    key = f"local/documents/{digest[:2]}/{digest}{path.suffix.lower()}"
    byte_size = path.stat().st_size
    stored = object_store.put_immutable(
        path=path, object_key=key, content_hash=digest, media_type=media_type
    )
    record = DocumentRevisionRecord(
        revision_id=f"DREV-{uuid4().hex}",
        document_id=document_id,
        content_hash=digest,
        source_filename=source_filename,
        object_key=stored.object_key,
        object_version_id=stored.version_id,
        media_type=media_type,
        byte_size=byte_size,
        source_id="SRC-USER-UPLOAD",
        authorization_status="用户授权上传",
        uploaded_by=actor.user_id,
        published_at=published_at,
    )
    uow.assets.add_revision(record)
    path.unlink(missing_ok=True)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="归档原文件",
        object_type="document_revision",
        object_id=record.revision_id,
        detail={"object_key": stored.object_key, "content_hash": digest},
    )
    return record, False


def create_run(uow: UnitOfWork, *, revision_id: str, settings: Settings) -> IngestionRunRecord:
    if uow.assets.get_revision(revision_id) is None:
        raise ValidationFailed("文档修订不存在")
    record = IngestionRunRecord(
        run_id=f"IRUN-{uuid4().hex}",
        revision_id=revision_id,
        parser_version="v2-ocr-table",
        chunker_version=settings.chunker_version,
        extractor_version=settings.extractor_version,
        embedding_version=settings.embedding_version,
    )
    uow.assets.add_run(record)
    return record


def create_reprocessing_job(
    uow: UnitOfWork,
    *,
    document_id: str,
    actor: Actor,
    settings: Settings,
):
    from app.services import ingestion

    document = uow.documents.get(document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.visibility_label not in actor.document_labels
    ):
        raise NotVisible("文档不存在或无访问权限")
    revision = uow.assets.find_revision_by_hash(document.content_hash)
    if revision is None:
        raise ValidationFailed("文档尚未建立 revision，无法重处理")
    if not revision.object_key:
        raise ValidationFailed("历史原件尚未归档对象存储，无法重处理；请先完成原件回填")
    run = create_run(uow, revision_id=revision.revision_id, settings=settings)
    return ingestion.create_job(
        uow,
        job_id=f"document-{document_id}-reprocess-{uuid4().hex[:12]}",
        document_id=document_id,
        path=None,
        source_filename=revision.source_filename,
        actor=actor,
        published_at=revision.published_at or document.published_at,
        security_id=document.security_id,
        thesis_id=None,
        view="",
        revision_id=revision.revision_id,
        object_key=revision.object_key,
        object_version_id=revision.object_version_id,
        upload_content_hash=revision.content_hash,
        ingestion_run_id=run.run_id,
    )


def mark_run_running(uow: UnitOfWork, run_id: str) -> None:
    record = uow.assets.get_run(run_id)
    if record:
        uow.assets.update_run(replace(record, status="running", started_at=now()))


def complete_run(
    uow: UnitOfWork,
    run_id: str,
    *,
    success: bool,
    result: dict[str, object],
) -> None:
    record = uow.assets.get_run(run_id)
    if not record:
        return
    updated = replace(
        record,
        status="succeeded" if success else "failed",
        segment_count=_integer(result.get("segment_count")),
        fact_count=_integer(result.get("fact_count")),
        event_count=_integer(result.get("event_count")),
        quality_summary={
            "duplicate": bool(result.get("duplicate")),
            "deferred_event_count": _integer(result.get("deferred_event_count")),
            "event_extraction_mode": result.get("event_extraction_mode", "none"),
        },
        error=None if success else str(result.get("reason") or "处理失败"),
        finished_at=now(),
    )
    uow.assets.update_run(updated)


def persist_artifacts(
    uow: UnitOfWork,
    *,
    run_id: str,
    segments: list,
    facts: list,
    document_id: str,
    visibility_label: str,
) -> None:
    records: list[IngestionArtifactRecord] = []
    for segment in segments:
        payload = {
            "locator": segment.locator,
            "ordinal": segment.ordinal,
            "content": segment.content,
            "page": segment.page,
            "content_kind": segment.content_kind,
            "extraction_method": segment.extraction_method,
        }
        records.append(_artifact(run_id, "segment", segment.locator, payload))
    for fact in facts:
        payload = {key: _json_value(value) for key, value in asdict(fact).items()}
        records.append(_artifact(run_id, "fact", fact.fact_id, payload))
    if records:
        uow.assets.add_artifacts(records)
        uow.assets.index_artifacts(
            run_id=run_id,
            document_id=document_id,
            visibility_label=visibility_label,
            records=records,
        )
        run = uow.assets.get_run(run_id)
        if run and run.embedding_version:
            uow.assets.upsert_embeddings(
                [
                    SegmentEmbeddingRecord(
                        index_id=f"{run_id}:{record.artifact_key}",
                        ingestion_run_id=run_id,
                        document_id=document_id,
                        locator=record.artifact_key,
                        embedding_version=run.embedding_version,
                        embedding=embed_text(
                            str(record.payload.get("content", "")),
                            version=run.embedding_version,
                        ),
                    )
                    for record in records
                    if record.artifact_type == "segment"
                ]
            )


def persist_event_artifacts(uow: UnitOfWork, *, run_id: str, events: list[EventRecord]) -> None:
    records = [
        _artifact(
            run_id,
            "event",
            event.event_id,
            {key: _json_value(value) for key, value in asdict(event).items()},
        )
        for event in events
    ]
    if records:
        uow.assets.add_artifacts(records)


def search_assets(
    uow: UnitOfWork, *, query: str, actor: Actor, limit: int = 20
) -> list[AssetSearchHitRecord]:
    normalized = query.strip()
    if not normalized:
        raise ValidationFailed("检索词不能为空")
    return uow.assets.search_segments(
        query=normalized,
        visibility_labels=tuple(sorted(actor.document_labels)),
        limit=max(1, min(limit, 100)),
    )


def embed_pending_assets(uow: UnitOfWork, *, embedding_version: str, batch_size: int = 500) -> int:
    """Incrementally add one embedding version without rewriting older vectors."""
    if not embedding_version:
        raise ValidationFailed("embedding_version 不能为空")
    sources = uow.assets.pending_embedding_sources(
        embedding_version=embedding_version, limit=max(1, min(batch_size, 5000))
    )
    return uow.assets.upsert_embeddings(
        [
            SegmentEmbeddingRecord(
                index_id=source.index_id,
                ingestion_run_id=source.ingestion_run_id,
                document_id=source.document_id,
                locator=source.locator,
                embedding_version=embedding_version,
                embedding=embed_text(source.content, version=embedding_version),
            )
            for source in sources
        ]
    )


def hybrid_retrieve(
    uow: UnitOfWork,
    *,
    query: str,
    actor: Actor,
    settings: Settings,
    security_ids: tuple[str, ...] = (),
    industries: tuple[str, ...] = (),
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    limit: int = 20,
) -> list[AssetSearchHitRecord]:
    """Permission-first hybrid retrieval for candidate context only.

    The repository applies visibility, security, industry and disclosure-time
    filters before ranking.  Results never bypass the human publication gate.
    """
    normalized = query.strip()
    if not normalized:
        raise ValidationFailed("检索词不能为空")
    if not settings.embedding_version:
        raise ValidationFailed("未配置 EMBEDDING_VERSION，混合召回不可用")
    if published_from and published_to and published_from > published_to:
        raise ValidationFailed("published_from 不能晚于 published_to")
    return uow.assets.hybrid_search_segments(
        query=normalized,
        query_embedding=embed_text(normalized, version=settings.embedding_version),
        embedding_version=settings.embedding_version,
        visibility_labels=tuple(sorted(actor.document_labels)),
        security_ids=security_ids,
        industries=industries,
        published_from=published_from,
        published_to=published_to,
        keyword_weight=settings.rag_hybrid_keyword_weight,
        vector_weight=settings.rag_hybrid_vector_weight,
        limit=max(1, min(limit, 100)),
    )


def change_document_visibility(
    uow: UnitOfWork,
    *,
    document_id: str,
    visibility_label: str,
    actor: Actor,
) -> None:
    _require_asset_operator(actor)
    if visibility_label not in {"公开", "内部", "内部受限", "机密"}:
        raise ValidationFailed("未知的文档权限标签")
    document = uow.documents.get(document_id)
    if document is None or document.deleted_at is not None:
        raise NotVisible("文档不存在或已删除")
    uow.documents.update_visibility(document_id, visibility_label)
    uow.assets.sync_document_visibility(document_id, visibility_label)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="变更文档权限",
        object_type="document",
        object_id=document_id,
        detail={"from": document.visibility_label, "to": visibility_label},
    )


def tombstone_document(uow: UnitOfWork, *, document_id: str, actor: Actor) -> None:
    """Soft-delete metadata and derived indexes; retained source objects stay immutable."""
    _require_asset_operator(actor)
    document = uow.documents.get(document_id)
    if document is None or document.deleted_at is not None:
        raise NotVisible("文档不存在或已删除")
    deleted_at = now()
    uow.documents.mark_deleted(document_id, deleted_at)
    uow.assets.remove_document_from_index(document_id)
    uow.assets.tombstone_revisions(document_id, deleted_at)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="删除文档资产",
        object_type="document",
        object_id=document_id,
        detail={
            "mode": "tombstone",
            "object_retained": True,
            "reason": "原件受保留策略与对象锁保护，仅同步移出活动索引",
        },
    )


def create_thesis_revision(
    uow: UnitOfWork, *, thesis_id: str, actor: Actor
) -> ThesisRevisionDraftRecord:
    thesis = uow.thesis.get(thesis_id)
    if thesis is None:
        raise NotVisible("投资逻辑不存在")
    if thesis.owner != actor.user_id:
        raise HumanGateRequired("只有负责人可以创建修订草稿")
    active = uow.assets.active_thesis_revision(thesis_id)
    if active:
        return active
    latest = uow.versions.latest(thesis_id)
    payload = latest.snapshot if latest else {"thesis": asdict(thesis)}
    draft = ThesisRevisionDraftRecord(
        draft_id=f"TRD-{uuid4().hex}",
        thesis_id=thesis_id,
        base_version=thesis.version,
        revision=1,
        owner=actor.user_id,
        payload=payload,
    )
    uow.assets.add_thesis_revision(draft)
    return draft


def update_thesis_revision(
    uow: UnitOfWork,
    *,
    draft_id: str,
    expected_revision: int,
    payload: dict[str, object],
    actor: Actor,
) -> ThesisRevisionDraftRecord:
    record = uow.assets.get_thesis_revision(draft_id)
    if record is None or record.owner != actor.user_id:
        raise NotVisible("修订草稿不存在或无访问权限")
    if record.status != "editing":
        raise ValidationFailed("修订草稿已关闭")
    if record.revision != expected_revision:
        raise ValidationFailed("修订草稿已被其他会话更新，请刷新后重试")
    updated = replace(record, payload=payload, revision=record.revision + 1)
    uow.assets.update_thesis_revision(updated)
    return updated


def publish_thesis_revision(
    uow: UnitOfWork,
    *,
    draft_id: str,
    expected_revision: int,
    reason: str,
    actor: Actor,
    settings: Settings,
) -> ThesisRevisionDraftRecord:
    record = uow.assets.get_thesis_revision(draft_id)
    if record is None or record.owner != actor.user_id:
        raise NotVisible("修订草稿不存在或无访问权限")
    if record.status != "editing":
        raise ValidationFailed("修订草稿已关闭")
    if record.revision != expected_revision:
        raise ValidationFailed("修订草稿已被其他会话更新，请刷新后重试")
    if not reason.strip():
        raise ValidationFailed("发布修订必须填写原因")
    thesis = uow.thesis.get(record.thesis_id)
    if thesis is None:
        raise NotVisible("投资逻辑不存在")
    latest = uow.versions.latest(record.thesis_id)
    current_version = latest.version if latest else thesis.version
    if current_version != record.base_version:
        raise ValidationFailed(
            f"基础版本 V{record.base_version} 已过期，当前为 V{current_version}，请重新建修订草稿"
        )
    if thesis.version != current_version:
        raise ValidationFailed(
            f"逻辑当前字段版本 V{thesis.version} 与快照 V{current_version} 不一致，请先完成数据修复"
        )

    thesis_payload = _mapping(record.payload.get("thesis"), "修订缺少 thesis 快照")
    updated_thesis = _updated_thesis(thesis, thesis_payload, version=current_version + 1)
    hypotheses = _updated_hypotheses(uow, record.thesis_id, record.payload.get("hypotheses"))
    if not any(item.importance is Importance.CORE for item in hypotheses):
        raise ValidationFailed("发布修订至少保留一条核心假设")
    mappings = _updated_mappings(uow, hypotheses, record.payload.get("metric_mappings"))

    uow.thesis.update(updated_thesis)
    for hypothesis in hypotheses:
        uow.thesis.update_hypothesis(hypothesis)
    for mapping in mappings:
        uow.thesis.update_mapping(mapping)
    evidence, data_cutoff_at, model_versions = version.evidence_snapshot(uow, record.thesis_id)
    base_snapshot = latest.snapshot if latest else {}
    diff_changes = revision_diff(record, base_snapshot)["changes"]
    changed_fields = list(diff_changes) if isinstance(diff_changes, dict) else []
    if record.payload.get("hypotheses") != base_snapshot.get("hypotheses"):
        changed_fields.append("hypotheses")
    if record.payload.get("metric_mappings") != base_snapshot.get("metric_mappings"):
        changed_fields.append("metric_mappings")
    version.create(
        uow.versions,
        thesis=updated_thesis,
        hypotheses=hypotheses,
        mappings=mappings,
        evidence=evidence,
        data_cutoff_at=data_cutoff_at,
        rule_version=settings.rules.version,
        model_versions=model_versions,
        triggered_by=version.TRIGGER_FIELD_EDIT,
        created_by=actor.user_id,
        change_reason=reason.strip(),
        changed_fields=sorted(set(changed_fields)),
    )
    published = replace(record, status="published", revision=record.revision + 1)
    uow.assets.update_thesis_revision(published)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="发布逻辑修订",
        object_type="thesis",
        object_id=record.thesis_id,
        detail={
            "draft_id": draft_id,
            "from_version": current_version,
            "to_version": current_version + 1,
            "reason": reason.strip(),
            "changed_fields": sorted(set(changed_fields)),
        },
    )
    return published


def revision_diff(record: ThesisRevisionDraftRecord, base: dict[str, object]) -> dict[str, object]:
    before_raw = base.get("thesis")
    after_raw = record.payload.get("thesis")
    before: dict[str, object] = dict(before_raw) if isinstance(before_raw, dict) else {}
    after: dict[str, object] = dict(after_raw) if isinstance(after_raw, dict) else {}
    changed = {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    }
    return {"draft_id": record.draft_id, "base_version": record.base_version, "changes": changed}


def _artifact(
    run_id: str, artifact_type: str, artifact_key: str, payload: dict[str, object]
) -> IngestionArtifactRecord:
    digest = sha256(repr(sorted(payload.items())).encode()).hexdigest()
    return IngestionArtifactRecord(run_id, artifact_type, artifact_key, payload, digest)


def _file_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value) if isinstance(value, Decimal) else value


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int | str) else 0


def _require_asset_operator(actor: Actor) -> None:
    if actor.user_id != "analyst-mvp" and "asset-admin" not in actor.teams:
        raise HumanGateRequired("只有资产管理员可以执行该操作")


def _mapping(value: object, message: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationFailed(message)
    return dict(value)


def _updated_thesis(thesis, payload: dict[str, object], *, version: int):
    title = str(payload.get("title", thesis.title)).strip()
    core_view = str(payload.get("core_view", thesis.core_view)).strip()
    direction = str(payload.get("direction", thesis.direction))
    if not title or len(title) > 40:
        raise ValidationFailed("修订标题须为 1 至 40 字")
    if not core_view or len(core_view) > 200:
        raise ValidationFailed("修订核心观点须为 1 至 200 字")
    if direction not in {"看多", "看空", "观察"}:
        raise ValidationFailed("修订投资方向无效")
    return replace(
        thesis,
        title=title,
        core_view=core_view,
        direction=direction,
        horizon_end_on=_date_value(payload.get("horizon_end_on"), thesis.horizon_end_on),
        next_review_at=_date_value(payload.get("next_review_at"), thesis.next_review_at),
        invalidation_require_all=bool(
            payload.get("invalidation_require_all", thesis.invalidation_require_all)
        ),
        version=version,
    )


def _updated_hypotheses(uow: UnitOfWork, thesis_id: str, payload: object):
    current = {item.hypothesis_id: item for item in uow.thesis.list_hypotheses(thesis_id)}
    if payload is None:
        return list(current.values())
    if not isinstance(payload, list):
        raise ValidationFailed("hypotheses 快照格式无效")
    if {str(item.get("hypothesis_id")) for item in payload if isinstance(item, dict)} != set(
        current
    ):
        raise ValidationFailed("修订必须保留全部既有假设 ID")
    updated = []
    for raw in payload:
        item = _mapping(raw, "hypothesis 快照格式无效")
        hypothesis = current[str(item["hypothesis_id"])]
        statement = str(item.get("statement", hypothesis.statement)).strip()
        if not statement:
            raise ValidationFailed("假设内容不能为空")
        updated.append(
            replace(
                hypothesis,
                statement=statement,
                hypothesis_type=str(item.get("hypothesis_type", hypothesis.hypothesis_type)),
                importance=Importance(str(item.get("importance", hypothesis.importance.value))),
                observation_window=_optional_text(item.get("observation_window")),
                invalidation_rule=_optional_text(item.get("invalidation_rule")),
                status=str(item.get("status", hypothesis.status)),
            )
        )
    return updated


def _updated_mappings(
    uow: UnitOfWork, hypotheses: list[HypothesisRecord], payload: object
) -> list[MetricMappingRecord]:
    current = {
        mapping.mapping_id: mapping
        for hypothesis in hypotheses
        for mapping in uow.thesis.list_mappings(hypothesis.hypothesis_id)
    }
    if payload is None:
        return list(current.values())
    if not isinstance(payload, list):
        raise ValidationFailed("metric_mappings 快照格式无效")
    if {str(item.get("mapping_id")) for item in payload if isinstance(item, dict)} != set(current):
        raise ValidationFailed("修订必须保留全部既有指标映射 ID")

    updated: list[MetricMappingRecord] = []
    for raw in payload:
        item = _mapping(raw, "metric_mapping 快照格式无效")
        mapping = current[str(item["mapping_id"])]
        if str(item.get("hypothesis_id", mapping.hypothesis_id)) != mapping.hypothesis_id:
            raise ValidationFailed("修订不能改变指标映射所属假设")
        if str(item.get("metric_id", mapping.metric_id)) != mapping.metric_id:
            raise ValidationFailed("修订不能替换指标映射的指标 ID")
        if str(item.get("metric_version", mapping.metric_version)) != mapping.metric_version:
            raise ValidationFailed("修订不能替换指标定义版本")
        if (
            str(item.get("confirmation_status", mapping.confirmation_status.value))
            != mapping.confirmation_status.value
        ):
            raise ValidationFailed("修订不能绕过指标映射确认流程")
        try:
            expected_direction = ExpectationDirection(
                str(item.get("expected_direction", mapping.expected_direction.value))
            )
        except ValueError as exc:
            raise ValidationFailed("指标预期方向无效") from exc
        periods = (
            _optional_integer(item["invalidation_consecutive_periods"])
            if "invalidation_consecutive_periods" in item
            else mapping.invalidation_consecutive_periods
        )
        if periods is not None and periods < 1:
            raise ValidationFailed("连续失效期数必须大于等于 1")
        updated.append(
            replace(
                mapping,
                expected_direction=expected_direction,
                expected_value=(
                    _optional_decimal(item["expected_value"])
                    if "expected_value" in item
                    else mapping.expected_value
                ),
                invalidation_threshold=(
                    _optional_decimal(item["invalidation_threshold"])
                    if "invalidation_threshold" in item
                    else mapping.invalidation_threshold
                ),
                invalidation_consecutive_periods=periods,
                expectation_source=_optional_text(
                    item.get("expectation_source", mapping.expectation_source)
                ),
            )
        )
    return updated


def _date_value(value: object, fallback: date | None) -> date | None:
    if value in (None, ""):
        return fallback
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationFailed(f"日期格式无效: {value}") from exc


def _optional_text(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationFailed(f"数值格式无效: {value}") from exc


def _optional_integer(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except ValueError as exc:
        raise ValidationFailed(f"整数格式无效: {value}") from exc
