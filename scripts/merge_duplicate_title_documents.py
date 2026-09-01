"""Merge title-index aliases into canonical full-text documents.

This command is intentionally conservative.  A merge is accepted only when:

* the source is an active ``标题索引`` document and the target is active full text;
* source and target have at least one byte-identical archived revision;
* a failed full-text ingestion run explicitly recorded the target as the duplicate;
* every evidence locator can be redirected to an existing canonical segment.

The source document is soft-deleted but its revisions and title segment remain available for
lineage.  Events and other source references are redirected, confirmed security relations are
copied, and immutable alias/thesis-relation artifacts plus audit records are appended.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select, text

from app.db.models.assets import (
    DocumentRevision,
    DocumentSecurityRelation,
    IngestionArtifact,
    IngestionRun,
)
from app.db.models.core import (
    Document,
    DocumentSegment,
    Event,
    Evidence,
    MetricObservation,
    Signal,
    Thesis,
)
from app.db.models.governance import AuditLog
from app.db.repositories.assets import SqlAssetRepo
from app.db.session import session_scope

ACTOR = "system:title-fulltext-dedup"


def _artifact_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()


def _replace_locator(locator: str, source_id: str, target_id: str) -> str:
    prefix = f"{source_id}#"
    if not locator.startswith(prefix):
        return locator
    return f"{target_id}#{locator.removeprefix(prefix)}"


def _replace_json(value: Any, source_id: str, target_id: str) -> Any:
    if isinstance(value, str):
        return _replace_locator(value, source_id, target_id)
    if isinstance(value, list):
        return [_replace_json(item, source_id, target_id) for item in value]
    if isinstance(value, dict):
        return {key: _replace_json(item, source_id, target_id) for key, item in value.items()}
    return value


def _validate(session: Any, source_id: str, target_id: str) -> tuple[Document, Document]:
    source = session.scalar(
        select(Document).where(Document.document_id == source_id).with_for_update()
    )
    target = session.scalar(
        select(Document).where(Document.document_id == target_id).with_for_update()
    )
    if source is None or target is None:
        raise ValueError("源文档或目标文档不存在")
    if source.deleted_at is not None:
        raise ValueError(f"源文档 {source_id} 已删除")
    if target.deleted_at is not None:
        raise ValueError(f"目标文档 {target_id} 已删除")
    if source.content_status != "标题索引":
        raise ValueError(f"源文档 {source_id} 不是标题索引")
    if target.content_status != "完整正文":
        raise ValueError(f"目标文档 {target_id} 不是完整正文")

    source_hashes = set(
        session.scalars(
            select(DocumentRevision.content_hash).where(
                DocumentRevision.canonical_document_id == source_id,
                DocumentRevision.object_key.is_not(None),
                DocumentRevision.tombstoned_at.is_(None),
            )
        )
    )
    target_hashes = set(
        session.scalars(
            select(DocumentRevision.content_hash).where(
                DocumentRevision.canonical_document_id == target_id,
                DocumentRevision.object_key.is_not(None),
                DocumentRevision.tombstoned_at.is_(None),
            )
        )
    )
    shared_hashes = source_hashes & target_hashes
    if not shared_hashes:
        raise ValueError("源文档与目标文档没有字节一致的活动归档原件")

    duplicate_failure = session.scalar(
        select(IngestionRun.run_id)
        .join(DocumentRevision, DocumentRevision.revision_id == IngestionRun.revision_id)
        .where(
            DocumentRevision.canonical_document_id == source_id,
            IngestionRun.status == "failed",
            IngestionRun.error.contains(f"现有文档 {target_id} 重复"),
        )
        .limit(1)
    )
    if duplicate_failure is None:
        raise ValueError("没有找到正文解析产生的目标重复校验记录")

    for locator in session.scalars(
        select(Evidence.evidence_locator).where(Evidence.source_document_id == source_id)
    ):
        canonical_locator = _replace_locator(locator, source_id, target_id)
        if canonical_locator == locator:
            raise ValueError(f"证据定位不属于源文档：{locator}")
        exists = session.scalar(
            select(DocumentSegment.id).where(
                DocumentSegment.document_id == target_id,
                DocumentSegment.locator == canonical_locator,
            )
        )
        if exists is None:
            raise ValueError(f"目标正文缺少证据对应定位：{canonical_locator}")
    return source, target


def _latest_successful_run(session: Any, document_id: str) -> IngestionRun:
    run = session.scalar(
        select(IngestionRun)
        .join(DocumentRevision, DocumentRevision.revision_id == IngestionRun.revision_id)
        .where(
            DocumentRevision.canonical_document_id == document_id,
            IngestionRun.status == "succeeded",
        )
        .order_by(IngestionRun.created_at.desc(), IngestionRun.run_id.desc())
        .limit(1)
    )
    if run is None:
        raise ValueError(f"目标文档 {document_id} 没有成功摄取运行，无法追加血缘制品")
    return run


def _append_artifact(
    session: Any,
    *,
    run_id: str,
    artifact_type: str,
    artifact_key: str,
    payload: dict[str, Any],
) -> None:
    exists = session.scalar(
        select(IngestionArtifact.id).where(
            IngestionArtifact.run_id == run_id,
            IngestionArtifact.artifact_type == artifact_type,
            IngestionArtifact.artifact_key == artifact_key,
        )
    )
    if exists is not None:
        return
    session.add(
        IngestionArtifact(
            run_id=run_id,
            artifact_type=artifact_type,
            artifact_key=artifact_key,
            payload=payload,
            content_hash=_artifact_hash(payload),
        )
    )


def merge(source_id: str, target_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    timestamp = datetime.now(UTC)
    with session_scope() as session:
        source, target = _validate(session, source_id, target_id)
        relations = list(
            session.scalars(
                select(DocumentSecurityRelation).where(
                    DocumentSecurityRelation.document_id == source_id,
                    DocumentSecurityRelation.status == "已确认",
                )
            )
        )
        evidence_rows = list(
            session.scalars(select(Evidence).where(Evidence.source_document_id == source_id))
        )
        event_rows = list(session.scalars(select(Event).where(Event.document_id == source_id)))
        if dry_run:
            return {
                "source_document_id": source_id,
                "target_document_id": target_id,
                "security_relations": len(relations),
                "events": len(event_rows),
                "evidence": len(evidence_rows),
                "status": "eligible",
            }

        if target.title == target.document_id and source.title:
            target.title = source.title
        if not target.security_id and source.security_id:
            target.security_id = source.security_id
        if not target.source_id and source.source_id:
            target.source_id = source.source_id
        if not target.doc_type and source.doc_type:
            target.doc_type = source.doc_type

        for relation in relations:
            exists = session.scalar(
                select(DocumentSecurityRelation.id).where(
                    DocumentSecurityRelation.document_id == target_id,
                    DocumentSecurityRelation.security_id == relation.security_id,
                    DocumentSecurityRelation.relation_type == relation.relation_type,
                )
            )
            if exists is None:
                session.add(
                    DocumentSecurityRelation(
                        document_id=target_id,
                        security_id=relation.security_id,
                        relation_type=relation.relation_type,
                        status=relation.status,
                        confidence=relation.confidence,
                        created_by=ACTOR,
                    )
                )

        for event in event_rows:
            sources = [item for item in (event.source_document_ids or []) if isinstance(item, str)]
            event.document_id = target_id
            event.source_document_ids = list(dict.fromkeys([target_id, *sources, source_id]))

        for evidence in evidence_rows:
            old_locator = evidence.evidence_locator
            evidence.source_document_id = target_id
            evidence.evidence_locator = _replace_locator(old_locator, source_id, target_id)
            if evidence.source_document_title == source.title:
                evidence.source_document_title = target.title
            note = f"正文去重归并：{source_id} -> {target_id}；原定位 {old_locator}。"
            evidence.review_note = f"{evidence.review_note or ''}\n{note}".strip()
            trace = dict(evidence.retrieval_trace or {})
            trace["document_alias_merge"] = {
                "source_document_id": source_id,
                "target_document_id": target_id,
                "source_locator": old_locator,
                "merged_at": timestamp.isoformat(),
            }
            evidence.retrieval_trace = trace

        for signal in session.scalars(
            select(Signal).where(Signal.evidence_locator.startswith(f"{source_id}#"))
        ):
            if signal.evidence_locator:
                signal.evidence_locator = _replace_locator(
                    signal.evidence_locator, source_id, target_id
                )

        for observation in session.scalars(
            select(MetricObservation).where(MetricObservation.source_document_id == source_id)
        ):
            observation.source_document_id = target_id
        for thesis in session.scalars(select(Thesis).where(Thesis.source_document_id == source_id)):
            thesis.source_document_id = target_id

        # Newer governance tables keep citation locators as JSON.  Update them without taking a
        # source-level dependency on optional model modules.
        for table_name, key_column in (
            ("logic_topic_relation", "relation_id"),
            ("ranking_prior_item", "id"),
        ):
            rows = session.execute(
                text(
                    f"SELECT {key_column}, citation_locators FROM {table_name} "
                    "WHERE citation_locators::text LIKE :needle"
                ),
                {"needle": f"%{source_id}%"},
            ).all()
            for row_id, locators in rows:
                session.execute(
                    text(
                        f"UPDATE {table_name} "
                        f"SET citation_locators=CAST(:value AS jsonb) WHERE {key_column}=:id"
                    ),
                    {
                        "id": row_id,
                        "value": json.dumps(_replace_json(locators, source_id, target_id)),
                    },
                )

        session.execute(
            text(
                "UPDATE document_processing_job SET document_id=:target "
                "WHERE document_id=:source"
            ),
            {"source": source_id, "target": target_id},
        )
        session.execute(
            text("UPDATE ingestion_review SET document_id=:target WHERE document_id=:source"),
            {"source": source_id, "target": target_id},
        )

        target_run = _latest_successful_run(session, target_id)
        alias_payload = {
            "source_document_id": source_id,
            "target_document_id": target_id,
            "relation_type": "byte_identical_archived_source",
            "status": "已归并",
            "merged_at": timestamp.isoformat(),
        }
        _append_artifact(
            session,
            run_id=target_run.run_id,
            artifact_type="document_alias",
            artifact_key=source_id,
            payload=alias_payload,
        )
        thesis_ids: list[str] = []
        for relation in relations:
            current_thesis = session.scalar(
                select(Thesis).where(
                    Thesis.security_id == relation.security_id,
                    Thesis.is_current.is_(True),
                )
            )
            if current_thesis is None:
                raise ValueError(f"证券 {relation.security_id} 没有当前投资逻辑")
            thesis_ids.append(current_thesis.thesis_id)
            relation_payload = {
                "document_id": target_id,
                "security_id": relation.security_id,
                "thesis_id": current_thesis.thesis_id,
                "relation_type": "security_current_thesis",
                "status": "已确认",
                "evidence_confirmation_status": "未生成",
                "source_alias_document_id": source_id,
            }
            _append_artifact(
                session,
                run_id=target_run.run_id,
                artifact_type="thesis_relation",
                artifact_key=current_thesis.thesis_id,
                payload=relation_payload,
            )

        SqlAssetRepo(session).remove_document_from_index(source_id)
        source.deleted_at = timestamp
        session.add_all(
            [
                AuditLog(
                    actor=ACTOR,
                    action="重复标题文档归并",
                    object_type="document",
                    object_id=source_id,
                    detail={**alias_payload, "thesis_ids": thesis_ids},
                ),
                AuditLog(
                    actor=ACTOR,
                    action="接收重复文档血缘",
                    object_type="document",
                    object_id=target_id,
                    detail={**alias_payload, "thesis_ids": thesis_ids},
                ),
            ]
        )
        return {
            "source_document_id": source_id,
            "target_document_id": target_id,
            "security_relations": len(relations),
            "events": len(event_rows),
            "evidence": len(evidence_rows),
            "thesis_ids": thesis_ids,
            "status": "merged",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_document_id")
    parser.add_argument("target_document_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            merge(
                args.source_document_id,
                args.target_document_id,
                dry_run=args.dry_run,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
