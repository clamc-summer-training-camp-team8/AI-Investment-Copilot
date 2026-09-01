from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient

from app.api.deps import get_settings, get_uow
from app.api.main import create_app
from app.core.config import Settings
from app.core.domain import AssetDocumentRecord, DocumentRevisionRecord, IngestionRunRecord
from tests.fakes import build_fake_uow

NOW = datetime.fromisoformat("2026-08-31T10:00:00+08:00")


@contextmanager
def _client() -> Iterator[TestClient]:
    uow = build_fake_uow()
    uow.assets.catalog_documents["DOC-1"] = AssetDocumentRecord(
        document_id="DOC-1",
        title="中芯国际年度报告",
        source_id="SRC-EXCHANGE",
        source_name="交易所公告",
        doc_type="年度报告",
        published_at=NOW,
        ingested_at=NOW,
        content_status="完整正文",
        visibility_label="内部",
        is_illustrative=False,
        deleted_at=None,
        archived=True,
        authorization_status="公开披露已核验",
        revision_count=1,
        segment_count=8,
        latest_run_status="succeeded",
        latest_run_at=NOW,
        security_ids=("688981",),
        security_names=("中芯国际",),
        industries=("芯片半导体",),
    )
    revision = DocumentRevisionRecord(
        revision_id="REV-1",
        document_id="DOC-1",
        canonical_document_id="DOC-1",
        content_hash="a" * 64,
        source_filename="report.pdf",
        object_key="documents/DOC-1/report.pdf",
        object_version_id="v1",
        media_type="application/pdf",
        byte_size=1024,
        authorization_status="公开披露已核验",
        content_status="完整正文",
        created_at=NOW,
    )
    uow.assets.add_revision(revision)
    uow.assets.add_run(
        IngestionRunRecord(
            run_id="RUN-1",
            revision_id="REV-1",
            parser_version="parser-v1",
            chunker_version="chunker-v1",
            extractor_version="extractor-v1",
            status="succeeded",
            segment_count=8,
            fact_count=3,
            event_count=1,
            created_at=NOW,
            finished_at=NOW,
        )
    )
    application = create_app()
    application.dependency_overrides[get_uow] = lambda: uow
    application.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    try:
        with TestClient(application, headers={"X-User-Id": "analyst-mvp"}) as client:
            yield client
    finally:
        application.dependency_overrides.clear()


def test_data_center_overview_catalog_detail_and_runs_form_one_api_contract() -> None:
    with _client() as client:
        overview = client.get("/api/assets/overview")
        catalog = client.get("/api/assets/documents", params={"q": "中芯", "security_id": "688981"})
        detail = client.get("/api/assets/documents/DOC-1")
        runs = client.get("/api/assets/ingestion-runs", params={"document_id": "DOC-1"})

    assert overview.status_code == 200, overview.text
    assert overview.json()["documents"] == 1
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["items"][0]["document_id"] == "DOC-1"
    assert detail.status_code == 200, detail.text
    assert detail.json()["revisions"][0]["has_object"] is True
    assert "reprocess" in detail.json()["allowed_actions"]
    assert runs.status_code == 200, runs.text
    assert runs.json()["items"][0]["run_id"] == "RUN-1"
