from __future__ import annotations

from datetime import datetime

import pytest

from app.core.domain import (
    AssetDocumentRecord,
    DocumentRecord,
    DocumentRevisionRecord,
    IngestionRunRecord,
)
from app.services import assets
from app.services.errors import HumanGateRequired, NotVisible
from app.services.permission import Actor
from tests.fakes import build_fake_uow

NOW = datetime.fromisoformat("2026-08-31T10:00:00+08:00")


def _document(
    document_id: str,
    *,
    visibility_label: str = "内部",
    title: str = "芯片公司年度报告",
    content_status: str = "完整正文",
    archived: bool = True,
    authorization_status: str = "公开披露已核验",
) -> AssetDocumentRecord:
    return AssetDocumentRecord(
        document_id=document_id,
        title=title,
        source_id="SRC-EXCHANGE",
        source_name="交易所公告",
        doc_type="年度报告",
        published_at=NOW,
        ingested_at=NOW,
        content_status=content_status,
        visibility_label=visibility_label,
        is_illustrative=False,
        deleted_at=None,
        archived=archived,
        authorization_status=authorization_status,
        revision_count=1,
        segment_count=12,
        latest_run_status="succeeded",
        latest_run_at=NOW,
        security_ids=("688981",),
        security_names=("中芯国际",),
        industries=("芯片半导体",),
    )


def _seed_revision_and_run(uow, document_id: str, run_id: str = "RUN-1") -> None:
    revision = DocumentRevisionRecord(
        revision_id=f"REV-{document_id}",
        document_id=document_id,
        canonical_document_id=document_id,
        content_hash="a" * 64,
        source_filename="report.pdf",
        object_key=f"documents/{document_id}/report.pdf",
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
            run_id=run_id,
            revision_id=revision.revision_id,
            parser_version="parser-v1",
            chunker_version="chunker-v1",
            extractor_version="extractor-v1",
            embedding_version="embed-v1",
            status="succeeded",
            segment_count=12,
            fact_count=4,
            event_count=2,
            created_at=NOW,
            finished_at=NOW,
        )
    )


def test_document_catalog_is_permission_first_and_supports_governed_filters() -> None:
    uow = build_fake_uow()
    uow.assets.catalog_documents["DOC-1"] = _document("DOC-1")
    uow.assets.catalog_documents["DOC-SECRET"] = _document(
        "DOC-SECRET", visibility_label="机密", title="未授权的并购资料"
    )
    _seed_revision_and_run(uow, "DOC-1")
    _seed_revision_and_run(uow, "DOC-SECRET", "RUN-SECRET")
    actor = Actor(user_id="researcher-1")

    records, total = assets.list_document_catalog(
        uow,
        actor=actor,
        query="芯片",
        content_status="完整正文",
        security_id="688981",
        industry="芯片半导体",
    )

    assert total == 1
    assert [item.document_id for item in records] == ["DOC-1"]
    with pytest.raises(NotVisible):
        assets.get_document_catalog(uow, document_id="DOC-SECRET", actor=actor)


def test_document_detail_exposes_lineage_and_role_scoped_actions() -> None:
    uow = build_fake_uow()
    uow.assets.catalog_documents["DOC-1"] = _document("DOC-1")
    _seed_revision_and_run(uow, "DOC-1")

    _, revisions, runs, reader_actions = assets.get_document_catalog(
        uow, document_id="DOC-1", actor=Actor(user_id="reader")
    )
    _, _, _, operator_actions = assets.get_document_catalog(
        uow, document_id="DOC-1", actor=Actor(user_id="analyst-mvp")
    )

    assert revisions[0].object_key is not None
    assert runs[0].segment_count == 12
    assert reader_actions == ["view_content"]
    assert {"view_content", "reprocess", "change_visibility", "delete"}.issubset(operator_actions)


def test_overview_and_run_center_do_not_count_invisible_assets() -> None:
    uow = build_fake_uow()
    uow.assets.catalog_documents["DOC-1"] = _document("DOC-1")
    uow.assets.catalog_documents["DOC-SECRET"] = _document(
        "DOC-SECRET", visibility_label="机密", archived=False, authorization_status="待确认"
    )
    _seed_revision_and_run(uow, "DOC-1")
    _seed_revision_and_run(uow, "DOC-SECRET", "RUN-SECRET")
    actor = Actor(user_id="reader")

    overview = assets.data_center_overview(uow, actor=actor)
    runs, total = assets.list_data_runs(uow, actor=actor, document_id="DOC-1", status="succeeded")

    assert overview["documents"] == 1
    assert overview["missing_archive_documents"] == 0
    assert overview["recent_succeeded_runs"] == 1
    assert total == 1
    assert runs[0].document_id == "DOC-1"


def test_deleted_document_can_only_be_restored_by_asset_operator() -> None:
    uow = build_fake_uow()
    deleted_at = NOW
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-DELETED",
            published_at=NOW,
            content_hash="b" * 64,
            parser_version="parser-v1",
            visibility_label="已删除",
            deleted_at=deleted_at,
        ),
        [],
        [],
    )
    uow.assets.add_revision(
        DocumentRevisionRecord(
            revision_id="REV-DELETED",
            document_id="DOC-DELETED",
            canonical_document_id="DOC-DELETED",
            content_hash="b" * 64,
            source_filename="deleted.pdf",
            tombstoned_at=deleted_at,
        )
    )

    with pytest.raises(HumanGateRequired):
        assets.restore_document(
            uow,
            document_id="DOC-DELETED",
            visibility_label="内部",
            actor=Actor(user_id="reader"),
        )

    indexed = assets.restore_document(
        uow,
        document_id="DOC-DELETED",
        visibility_label="内部受限",
        actor=Actor(user_id="analyst-mvp"),
    )

    assert indexed == 0
    assert uow.documents.get("DOC-DELETED").deleted_at is None
    assert uow.documents.get("DOC-DELETED").visibility_label == "内部受限"
    assert uow.assets.get_revision("REV-DELETED").tombstoned_at is None
    assert "恢复文档资产" in uow.audit.actions()
