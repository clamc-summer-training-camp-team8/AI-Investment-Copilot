from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.domain import (
    DocumentRecord,
    DocumentRevisionRecord,
    IngestionRunRecord,
    SourceRecord,
)
from app.core.timeutil import now
from app.db.repositories import build_uow

pytestmark = pytest.mark.integration


def test_data_center_catalog_lineage_sources_and_runs_round_trip_in_postgres(
    session: Session,
) -> None:
    suffix = uuid4().hex[:12]
    source_id = f"SRC-DC-{suffix}"
    document_id = f"DOC-DC-{suffix}"
    secret_document_id = f"DOC-DC-SECRET-{suffix}"
    revision_id = f"REV-DC-{suffix}"
    run_id = f"RUN-DC-{suffix}"
    timestamp = now()
    uow = build_uow(session)
    before = uow.assets.catalog_overview(visibility_labels=("内部",))
    uow.assets.add_source(
        SourceRecord(
            source_id=source_id,
            name="交易所公告",
            source_type="exchange",
            authorization_status="公开披露已核验",
            base_url="https://example.test/disclosures",
        )
    )
    uow.documents.add(
        DocumentRecord(
            document_id=document_id,
            title="芯片公司年度报告",
            source_id=source_id,
            doc_type="年度报告",
            published_at=timestamp,
            content_hash=("a" + suffix).ljust(64, "a"),
            parser_version="parser-v1",
            body="年度报告正文与经营数据",
            visibility_label="内部",
            content_status="完整正文",
        ),
        [],
        [],
    )
    uow.documents.add(
        DocumentRecord(
            document_id=secret_document_id,
            title="未授权机密资料",
            source_id=source_id,
            doc_type="内部材料",
            published_at=timestamp,
            content_hash=("b" + suffix).ljust(64, "b"),
            parser_version="parser-v1",
            visibility_label="机密",
            content_status="标题索引",
        ),
        [],
        [],
    )
    uow.assets.add_revision(
        DocumentRevisionRecord(
            revision_id=revision_id,
            document_id=document_id,
            canonical_document_id=document_id,
            content_hash=("c" + suffix).ljust(64, "c"),
            source_filename="annual-report.pdf",
            object_key=f"documents/{document_id}/annual-report.pdf",
            object_version_id="v1",
            media_type="application/pdf",
            byte_size=2048,
            source_id=source_id,
            authorization_status="公开披露已核验",
            content_status="完整正文",
            published_at=timestamp,
            created_at=timestamp,
        )
    )
    uow.assets.add_run(
        IngestionRunRecord(
            run_id=run_id,
            revision_id=revision_id,
            parser_version="parser-v1",
            chunker_version="chunker-v1",
            extractor_version="extractor-v1",
            embedding_version="embed-v1",
            status="succeeded",
            segment_count=8,
            fact_count=3,
            event_count=1,
            quality_summary={"locator_coverage": 1},
            started_at=timestamp,
            finished_at=timestamp,
            created_at=timestamp,
        )
    )

    documents, total = uow.assets.list_documents(
        visibility_labels=("内部",),
        query="芯片",
        content_status="完整正文",
        source_id=source_id,
        doc_type="年度报告",
        security_id=None,
        industry=None,
        authorization_status="公开披露已核验",
        archived=True,
        run_status="succeeded",
        visibility_label=None,
        published_from=None,
        published_to=None,
        include_deleted=False,
        sort="published_at",
        direction="desc",
        limit=20,
        offset=0,
    )
    detail = uow.assets.get_document_catalog(
        document_id, visibility_labels=("内部",), include_deleted=False
    )
    revisions = uow.assets.list_document_revisions(document_id)
    runs = uow.assets.list_document_runs(document_id)
    run_page, run_total = uow.assets.list_ingestion_runs(
        visibility_labels=("内部",),
        status="succeeded",
        document_id=document_id,
        limit=20,
        offset=0,
    )
    sources = uow.assets.list_sources(visibility_labels=("内部",))
    overview = uow.assets.catalog_overview(visibility_labels=("内部",))

    assert total == 1
    assert documents[0].document_id == document_id
    assert detail and detail.archived is True
    assert detail.authorization_status == "公开披露已核验"
    assert [item.revision_id for item in revisions] == [revision_id]
    assert [item.run_id for item in runs] == [run_id]
    assert run_total == 1 and run_page[0].document_id == document_id
    assert any(item.source_id == source_id and item.document_count == 1 for item in sources)
    assert overview["documents"] == before["documents"] + 1
    assert overview["recent_succeeded_runs"] == before["recent_succeeded_runs"] + 1
