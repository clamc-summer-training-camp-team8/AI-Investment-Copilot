from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.domain import (
    DocumentRecord,
    DocumentRevisionRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ThesisRecord,
    VersionRecord,
)
from app.core.enums import ExpectationDirection, Importance, ThesisStatus
from app.services import assets
from app.services.errors import ValidationFailed
from app.services.object_store import StoredObject
from app.services.permission import Actor
from tests.fakes import build_fake_uow


class MemoryObjectStore:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}

    def put_immutable(
        self, *, path: Path, object_key: str, content_hash: str, media_type: str | None
    ) -> StoredObject:
        self.saved[object_key] = path.read_bytes()
        return StoredObject(object_key, "v1", "etag")


def test_archive_upload_is_hash_addressed_and_removes_spool(tmp_path: Path) -> None:
    path = tmp_path / "report.txt"
    path.write_text("不可变原件", encoding="utf-8")
    uow = build_fake_uow()
    store = MemoryObjectStore()

    revision, duplicate = assets.archive_upload(
        uow,
        path=path,
        document_id="DOC-1",
        source_filename="report.txt",
        media_type="text/plain",
        published_at=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        actor=Actor(user_id="researcher-1"),
        object_store=store,  # type: ignore[arg-type]
    )

    assert duplicate is False
    assert revision.object_key and revision.content_hash in revision.object_key
    assert revision.object_version_id == "v1"
    assert path.exists() is False


def test_same_source_object_gets_append_only_revision_for_each_document(tmp_path: Path) -> None:
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_text("同一不可变原件", encoding="utf-8")
    second_path.write_text("同一不可变原件", encoding="utf-8")
    uow = build_fake_uow()
    store = MemoryObjectStore()
    actor = Actor(user_id="researcher-1")

    first, first_duplicate = assets.archive_upload(
        uow,
        path=first_path,
        document_id="DOC-1",
        source_filename="first.txt",
        media_type="text/plain",
        published_at=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        actor=actor,
        object_store=store,  # type: ignore[arg-type]
    )
    second, second_duplicate = assets.archive_upload(
        uow,
        path=second_path,
        document_id="DOC-2",
        source_filename="second.txt",
        media_type="text/plain",
        published_at=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
        actor=actor,
        object_store=store,  # type: ignore[arg-type]
    )

    assert first_duplicate is False
    assert second_duplicate is True
    assert first.revision_id != second.revision_id
    assert first.object_key == second.object_key
    assert second.document_id == "DOC-2"
    assert len(uow.assets.revisions) == 2


def test_ingestion_runs_are_append_only_for_reprocessing() -> None:
    uow = build_fake_uow()
    uow.assets.add_revision(
        DocumentRevisionRecord(
            revision_id="DREV-1",
            document_id="DOC-1",
            content_hash="a" * 64,
            source_filename="report.txt",
        )
    )
    settings = Settings(_env_file=None)

    first = assets.create_run(uow, revision_id="DREV-1", settings=settings)
    second = assets.create_run(uow, revision_id="DREV-1", settings=settings)

    assert first.run_id != second.run_id
    assert len(uow.assets.runs) == 2


def test_thesis_revision_uses_optimistic_concurrency() -> None:
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-1",
            security_id="600000.SH",
            title="基准逻辑",
            direction="观察",
            core_view="原观点",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
            version=1,
        )
    )
    uow.versions.add(
        VersionRecord(
            thesis_id="THS-1",
            version=1,
            snapshot={"thesis": {"core_view": "原观点"}},
            triggered_by="发布",
            created_by="researcher-1",
        )
    )
    actor = Actor(user_id="researcher-1")
    draft = assets.create_thesis_revision(uow, thesis_id="THS-1", actor=actor)
    updated = assets.update_thesis_revision(
        uow,
        draft_id=draft.draft_id,
        expected_revision=1,
        payload={"thesis": {"core_view": "新观点"}},
        actor=actor,
    )
    assert updated.revision == 2
    assert assets.revision_diff(updated, {"thesis": {"core_view": "原观点"}})["changes"]

    with pytest.raises(ValidationFailed):
        assets.update_thesis_revision(
            uow,
            draft_id=draft.draft_id,
            expected_revision=1,
            payload={},
            actor=actor,
        )


def test_published_revision_creates_new_frozen_version() -> None:
    uow = build_fake_uow()
    thesis = ThesisRecord(
        thesis_id="THS-REV-1",
        security_id="600000.SH",
        title="原标题",
        direction="观察",
        core_view="原观点",
        established_on=date(2026, 1, 1),
        owner="researcher-1",
        status=ThesisStatus.VALIDATING,
        version=1,
    )
    hypothesis = HypothesisRecord(
        hypothesis_id="H-REV-1",
        thesis_id=thesis.thesis_id,
        statement="原假设",
        hypothesis_type="经营",
        importance=Importance.CORE,
    )
    uow.thesis.add(thesis)
    uow.thesis.add_hypothesis(hypothesis)
    mapping = MetricMappingRecord(
        mapping_id="MAP-REV-1",
        hypothesis_id=hypothesis.hypothesis_id,
        metric_id="MET-REV-1",
        expected_direction=ExpectationDirection.HIGHER_BETTER,
        expected_value=Decimal("10"),
        invalidation_threshold=Decimal("8"),
    )
    uow.thesis.add_mapping(mapping)
    uow.versions.add(
        VersionRecord(
            thesis_id=thesis.thesis_id,
            version=1,
            snapshot={
                "thesis": {
                    "title": thesis.title,
                    "core_view": thesis.core_view,
                    "direction": thesis.direction,
                },
                "hypotheses": [
                    {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "statement": hypothesis.statement,
                        "hypothesis_type": hypothesis.hypothesis_type,
                        "importance": hypothesis.importance.value,
                        "status": hypothesis.status,
                    }
                ],
                "metric_mappings": [
                    {
                        "mapping_id": mapping.mapping_id,
                        "hypothesis_id": mapping.hypothesis_id,
                        "metric_id": mapping.metric_id,
                        "expected_direction": mapping.expected_direction.value,
                        "metric_version": mapping.metric_version,
                        "expected_value": "10",
                        "invalidation_threshold": "8",
                        "invalidation_consecutive_periods": None,
                        "expectation_source": None,
                        "confirmation_status": mapping.confirmation_status.value,
                    }
                ],
            },
            triggered_by="发布",
            created_by="researcher-1",
        )
    )
    actor = Actor(user_id="researcher-1")
    draft = assets.create_thesis_revision(uow, thesis_id=thesis.thesis_id, actor=actor)
    payload = dict(draft.payload)
    payload["thesis"] = {**payload["thesis"], "core_view": "修订后的观点"}
    payload["metric_mappings"] = [
        {
            **payload["metric_mappings"][0],
            "expected_value": "12.5",
            "invalidation_threshold": "9",
            "invalidation_consecutive_periods": 2,
            "expectation_source": "2026 年修订基准",
        }
    ]
    saved = assets.update_thesis_revision(
        uow,
        draft_id=draft.draft_id,
        expected_revision=draft.revision,
        payload=payload,
        actor=actor,
    )
    published = assets.publish_thesis_revision(
        uow,
        draft_id=draft.draft_id,
        expected_revision=saved.revision,
        reason="新证据改变判断",
        actor=actor,
        settings=Settings(_env_file=None),
    )

    assert published.status == "published"
    assert uow.thesis.get(thesis.thesis_id).core_view == "修订后的观点"
    latest = uow.versions.latest(thesis.thesis_id)
    assert latest and latest.version == 2
    assert latest.snapshot["rule_version"] == "rules-v1"
    assert latest.snapshot["metric_mappings"][0]["expected_value"] == "12.5"
    persisted_mapping = uow.thesis.list_mappings(hypothesis.hypothesis_id)[0]
    assert persisted_mapping.expected_value == Decimal("12.5")
    assert persisted_mapping.invalidation_consecutive_periods == 2


def test_revision_publish_rejects_stale_base_version() -> None:
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-STALE-1",
            security_id="600000.SH",
            title="基准",
            direction="观察",
            core_view="观点",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
            version=1,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="H-STALE-1",
            thesis_id="THS-STALE-1",
            statement="核心假设",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    uow.versions.add(
        VersionRecord(
            thesis_id="THS-STALE-1",
            version=1,
            snapshot={"thesis": {"title": "基准"}},
            triggered_by="发布",
            created_by="researcher-1",
        )
    )
    actor = Actor(user_id="researcher-1")
    draft = assets.create_thesis_revision(uow, thesis_id="THS-STALE-1", actor=actor)
    uow.versions.add(
        VersionRecord(
            thesis_id="THS-STALE-1",
            version=2,
            snapshot={"thesis": {"title": "其他会话已发布"}},
            triggered_by="字段修改",
            created_by="researcher-1",
        )
    )

    with pytest.raises(ValidationFailed, match="基础版本 V1 已过期"):
        assets.publish_thesis_revision(
            uow,
            draft_id=draft.draft_id,
            expected_revision=draft.revision,
            reason="尝试覆盖",
            actor=actor,
            settings=Settings(_env_file=None),
        )


def test_asset_visibility_and_tombstone_sync_require_operator() -> None:
    uow = build_fake_uow()
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-ASSET-1",
            published_at=datetime.fromisoformat("2026-08-12T09:00:00+08:00"),
            content_hash="b" * 64,
            parser_version="v2",
        ),
        [],
        [],
    )
    operator = Actor(user_id="analyst-mvp")
    assets.change_document_visibility(
        uow,
        document_id="DOC-ASSET-1",
        visibility_label="内部受限",
        actor=operator,
    )
    assert uow.documents.get("DOC-ASSET-1").visibility_label == "内部受限"

    assets.tombstone_document(uow, document_id="DOC-ASSET-1", actor=operator)
    assert uow.documents.get("DOC-ASSET-1").deleted_at is not None
