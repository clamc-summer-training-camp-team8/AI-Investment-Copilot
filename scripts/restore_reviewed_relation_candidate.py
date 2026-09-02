"""从同主机隔离恢复库受控恢复已冻结关系候选；复核结论由独立回执脚本应用。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.core import (
    Document,
    DocumentSegment,
    Event,
    Evidence,
    EvidenceRelation,
    Hypothesis,
    Security,
    Thesis,
)
from app.db.models.governance import AuditLog
from app.db.session import session_scope
from scripts.apply_relation_review_receipt import (
    DEFAULT_RECEIPT,
    load_and_validate_receipt,
    parse_relation_review,
)

ModelT = TypeVar("ModelT")
_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _column_values(row: object, *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns  # type: ignore[attr-defined]
        if column.name not in exclude
    }


def _assert_equal_rows(
    *,
    label: str,
    expected: object,
    actual: object,
    exclude: frozenset[str] = frozenset(),
) -> None:
    expected_values = _column_values(expected, exclude=exclude)
    actual_values = _column_values(actual, exclude=exclude)
    drift = sorted(
        key for key, value in expected_values.items() if actual_values.get(key) != value
    )
    if drift:
        raise ValueError(f"{label} 已存在但字段漂移: {drift}")


def _validate_candidate_snapshot(
    snapshot: dict[str, Any], receipt_payload: dict[str, Any]
) -> dict[str, Any]:
    candidate = snapshot.get("candidate_relation")
    subject = receipt_payload["subject"]
    expected = receipt_payload["expected_candidate"]
    if not isinstance(candidate, dict):
        raise ValueError("候选快照缺少 candidate_relation")
    comparisons = {
        "relation_id": subject["relation_id"],
        "evidence_id": subject["evidence_id"],
        "security_id": subject["security_id"],
        "thesis_id": subject["thesis_id"],
        "hypothesis_id": subject["hypothesis_id"],
        "status": expected["status"],
        "candidate_direction": expected["direction"],
        "candidate_strength": expected.get("strength"),
        "candidate_reason": expected.get("reason"),
    }
    drift = sorted(key for key, value in comparisons.items() if candidate.get(key) != value)
    if drift:
        raise ValueError(f"候选快照与复核回执不一致: {drift}")
    if snapshot.get("read_only_snapshot") is not True:
        raise ValueError("候选快照未声明 read_only_snapshot")
    return candidate


def _source_url(source_database: str):
    if not _DATABASE_NAME.fullmatch(source_database):
        raise ValueError("source-database 只能包含字母、数字和下划线")
    target_url = make_url(settings.database_url)
    if target_url.database == source_database:
        raise ValueError("源数据库不得与目标数据库相同")
    return target_url.set(database=source_database)


def _required(session: Session, model: type[ModelT], object_id: str, *, label: str) -> ModelT:
    row = session.get(model, object_id)
    if row is None:
        raise ValueError(f"{label}不存在: {object_id}")
    return row


def _copy_primary_row(
    target: Session,
    *,
    model: type[ModelT],
    source_row: ModelT,
    object_id: str,
    label: str,
    apply: bool,
    changes: list[str],
) -> None:
    existing = target.get(model, object_id)
    if existing is not None:
        _assert_equal_rows(label=label, expected=source_row, actual=existing)
        return
    changes.append(label)
    if apply:
        target.add(model(**_column_values(source_row)))
        target.flush()


def _copy_segments(
    source: Session,
    target: Session,
    *,
    document_id: str,
    apply: bool,
    changes: list[str],
) -> int:
    rows = source.scalars(
        select(DocumentSegment)
        .where(DocumentSegment.document_id == document_id)
        .order_by(DocumentSegment.ordinal, DocumentSegment.id)
    ).all()
    if not rows:
        raise ValueError(f"源文档没有切片: {document_id}")
    inserted_count = 0
    for row in rows:
        existing = target.scalar(
            select(DocumentSegment).where(
                DocumentSegment.document_id == document_id,
                DocumentSegment.locator == row.locator,
            )
        )
        if existing is not None:
            _assert_equal_rows(
                label=f"文档切片 {row.locator}",
                expected=row,
                actual=existing,
                exclude=frozenset({"id"}),
            )
            continue
        if apply:
            target.add(DocumentSegment(**_column_values(row, exclude=frozenset({"id"}))))
        inserted_count += 1
    if inserted_count and apply:
        target.flush()
    if inserted_count:
        changes.append(f"document_segment:{inserted_count}")
    return len(rows)


def _validate_source_review(source_relation: EvidenceRelation, receipt_payload: dict[str, Any]) -> None:
    review = parse_relation_review(receipt_payload)
    expected = {
        "status": "已确认",
        "direction": review.final_direction.value,
        "strength": review.final_strength,
        "reason": review.final_reason,
        "reviewed_by": review.reviewer_id,
        "reviewed_at": review.reviewed_at,
    }
    drift = sorted(
        key for key, value in expected.items() if getattr(source_relation, key) != value
    )
    if drift:
        raise ValueError(f"隔离恢复库中的已复核关系与回执不一致: {drift}")


def restore_candidate(
    *,
    source_database: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    operator: str,
    apply: bool,
) -> dict[str, Any]:
    receipt_payload, receipt_sha256 = load_and_validate_receipt(
        receipt_path, expected_sha256=expected_receipt_sha256
    )
    candidate_snapshot_path = receipt_path.resolve().parent / "candidate_snapshot.json"
    snapshot = json.loads(candidate_snapshot_path.read_text(encoding="utf-8"))
    candidate = _validate_candidate_snapshot(snapshot, receipt_payload)
    subject = receipt_payload["subject"]
    document_id = str(snapshot["secondary_source"]["document_id"])

    source_engine = create_engine(
        _source_url(source_database),
        pool_pre_ping=True,
        connect_args={"connect_timeout": 5},
        future=True,
    )
    changes: list[str] = []
    try:
        with Session(source_engine) as source, session_scope() as target:
            source_document = _required(
                source, Document, document_id, label="源文档"
            )
            source_event_id = str(
                _required(
                    source,
                    Evidence,
                    str(subject["evidence_id"]),
                    label="源证据",
                ).event_id
            )
            source_event = _required(source, Event, source_event_id, label="源事件")
            source_evidence = _required(
                source, Evidence, str(subject["evidence_id"]), label="源证据"
            )
            source_relation = _required(
                source,
                EvidenceRelation,
                str(subject["relation_id"]),
                label="源关系",
            )
            _validate_source_review(source_relation, receipt_payload)
            if source_evidence.source_document_id != document_id:
                raise ValueError("源证据引用文档与候选快照不一致")
            if source_event.document_id != document_id:
                raise ValueError("源事件引用文档与候选快照不一致")

            _required(target, Security, str(subject["security_id"]), label="目标证券")
            _required(target, Thesis, str(subject["thesis_id"]), label="目标投资逻辑")
            _required(target, Hypothesis, str(subject["hypothesis_id"]), label="目标假设")

            duplicate_document = target.scalar(
                select(Document).where(
                    Document.content_hash == source_document.content_hash,
                    Document.parser_version == source_document.parser_version,
                    Document.document_id != document_id,
                )
            )
            if duplicate_document is not None:
                raise ValueError(
                    f"目标库已有相同文档内容但编号不同: {duplicate_document.document_id}"
                )
            duplicate_event = target.scalar(
                select(Event).where(
                    Event.fingerprint == source_event.fingerprint,
                    Event.event_id != source_event.event_id,
                )
            )
            if duplicate_event is not None:
                raise ValueError(
                    f"目标库已有相同事件指纹但编号不同: {duplicate_event.event_id}"
                )

            existing_relation = target.get(EvidenceRelation, str(subject["relation_id"]))
            already_reviewed = False
            if existing_relation is not None:
                try:
                    _validate_source_review(existing_relation, receipt_payload)
                    already_reviewed = True
                except ValueError as source_review_error:
                    expected_pending = {
                        "evidence_id": subject["evidence_id"],
                        "thesis_id": subject["thesis_id"],
                        "hypothesis_id": subject["hypothesis_id"],
                        "status": candidate["status"],
                        "direction": candidate["candidate_direction"],
                        "strength": candidate.get("candidate_strength"),
                        "reason": candidate.get("candidate_reason"),
                        "created_by": candidate["created_by"],
                    }
                    drift = sorted(
                        key
                        for key, value in expected_pending.items()
                        if getattr(existing_relation, key) != value
                    )
                    if drift:
                        raise ValueError(
                            f"目标关系已存在但候选字段漂移: {drift}"
                        ) from source_review_error

            _copy_primary_row(
                target,
                model=Document,
                source_row=source_document,
                object_id=document_id,
                label=f"document:{document_id}",
                apply=apply,
                changes=changes,
            )
            segment_count = _copy_segments(
                source,
                target,
                document_id=document_id,
                apply=apply,
                changes=changes,
            )
            _copy_primary_row(
                target,
                model=Event,
                source_row=source_event,
                object_id=source_event.event_id,
                label=f"event:{source_event.event_id}",
                apply=apply,
                changes=changes,
            )
            _copy_primary_row(
                target,
                model=Evidence,
                source_row=source_evidence,
                object_id=source_evidence.evidence_id,
                label=f"evidence:{source_evidence.evidence_id}",
                apply=apply,
                changes=changes,
            )
            if existing_relation is None:
                changes.append(f"evidence_relation:{candidate['relation_id']}")
                if apply:
                    created_at = datetime.fromisoformat(str(candidate["created_at"]))
                    target.add(
                        EvidenceRelation(
                            relation_id=str(candidate["relation_id"]),
                            evidence_id=str(candidate["evidence_id"]),
                            thesis_id=str(candidate["thesis_id"]),
                            hypothesis_id=str(candidate["hypothesis_id"]),
                            direction=str(candidate["candidate_direction"]),
                            strength=candidate.get("candidate_strength"),
                            reason=candidate.get("candidate_reason"),
                            status=str(candidate["status"]),
                            created_by=str(candidate["created_by"]),
                            reviewed_by=None,
                            reviewed_at=None,
                            deactivated_by=None,
                            deactivated_at=None,
                            created_at=created_at,
                            updated_at=created_at,
                        )
                    )
                    target.flush()
            if apply and changes:
                target.add(
                    AuditLog(
                        actor=operator,
                        action="restore_relation_candidate",
                        object_type="evidence_relation",
                        object_id=str(candidate["relation_id"]),
                        detail={
                            "source_database": source_database,
                            "receipt_sha256": receipt_sha256,
                            "inserted": changes,
                            "segment_count": segment_count,
                            "relation_already_reviewed": already_reviewed,
                        },
                    )
                )

            return {
                "mode": "apply" if apply else "dry-run",
                "source_database": source_database,
                "target_database": make_url(settings.database_url).database,
                "relation_id": candidate["relation_id"],
                "security_id": subject["security_id"],
                "document_id": document_id,
                "source_candidate_verified": True,
                "source_review_verified": True,
                "already_reviewed_in_target": already_reviewed,
                "planned_changes": changes,
                "database_write_performed": bool(apply and changes),
            }
    finally:
        source_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--operator", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = restore_candidate(
        source_database=args.source_database,
        receipt_path=args.receipt,
        expected_receipt_sha256=args.expected_receipt_sha256,
        operator=args.operator,
        apply=args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
