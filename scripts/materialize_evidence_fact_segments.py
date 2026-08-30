"""Materialize existing evidence excerpts as searchable, traceable document segments.

This is a lossless projection: it does not create evidence, change direction, or
promote confirmation status.  Reviewed primary-source body locators are preserved.
"""

from __future__ import annotations

import argparse
import hashlib
import json

from sqlalchemy import select

from app.db.models.assets import DocumentSecurityRelation
from app.db.models.core import Document, DocumentSegment, Evidence
from app.db.session import session_scope


def _locator(document_id: str, direction: str, excerpt: str) -> str:
    digest = hashlib.sha256(f"{direction}|{excerpt}".encode("utf-8")).hexdigest()[:16]
    return f"{document_id}#evidence-{digest}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--security-id", action="append", dest="security_ids")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    created_segments = updated_locators = created_relations = preserved_reviewed = skipped = 0
    with session_scope() as session:
        relation_keys = set(
            session.execute(
                select(
                    DocumentSecurityRelation.document_id,
                    DocumentSecurityRelation.security_id,
                    DocumentSecurityRelation.relation_type,
                )
            ).all()
        )
        segment_locators = set(session.scalars(select(DocumentSegment.locator)).all())
        statement = select(Evidence).where(
            Evidence.source_document_id.is_not(None),
            Evidence.fact_excerpt.is_not(None),
        )
        if args.security_ids:
            statement = statement.where(Evidence.security_id.in_(args.security_ids))
        evidences = session.scalars(statement.order_by(Evidence.evidence_id)).all()
        for evidence in evidences:
            document_id = str(evidence.source_document_id)
            document = session.get(Document, document_id)
            if document is None or not evidence.security_id or not evidence.fact_excerpt:
                skipped += 1
                continue

            relation_key = (document_id, evidence.security_id, "主体")
            if relation_key not in relation_keys:
                created_relations += 1
                relation_keys.add(relation_key)
                if args.apply:
                    session.add(
                        DocumentSecurityRelation(
                            document_id=document_id,
                            security_id=evidence.security_id,
                            relation_type="主体",
                            status="已确认",
                            confidence=1,
                            created_by="evidence-fact-materializer",
                        )
                    )

            current = session.scalar(
                select(DocumentSegment).where(DocumentSegment.locator == evidence.evidence_locator)
            )
            if current is not None and current.extraction_method == "reviewed_body":
                preserved_reviewed += 1
                continue

            locator = _locator(document_id, evidence.direction, evidence.fact_excerpt)
            if locator not in segment_locators:
                created_segments += 1
                segment_locators.add(locator)
                if args.apply:
                    ordinal = 1000 + int(locator.rsplit("-", 1)[-1][:6], 16)
                    session.add(
                        DocumentSegment(
                            document_id=document_id,
                            locator=locator,
                            ordinal=ordinal,
                            content=(
                                f"【候选证据｜{evidence.direction}｜未人工确认】"
                                f"{evidence.fact_excerpt}"
                            ),
                            content_kind="paragraph",
                            extraction_method="evidence_fact",
                            confidence=evidence.ai_confidence,
                        )
                    )
            if evidence.evidence_locator != locator:
                updated_locators += 1
                if args.apply:
                    evidence.evidence_locator = locator

        if not args.apply:
            session.rollback()
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry_run",
                "segments_created": created_segments,
                "evidence_locators_updated": updated_locators,
                "document_relations_created": created_relations,
                "reviewed_body_locators_preserved": preserved_reviewed,
                "skipped": skipped,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
