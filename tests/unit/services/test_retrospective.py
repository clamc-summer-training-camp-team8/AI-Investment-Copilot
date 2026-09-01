from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.core.config import Settings
from app.core.domain import (
    DocumentRecord,
    DocumentRevisionRecord,
    EvidenceRecord,
    EvidenceRelationRecord,
    HypothesisRecord,
    RetrospectiveSourceRecord,
    SecurityRecord,
    ThesisRecord,
    VersionRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    DocumentContentStatus,
    ImpactDirection,
    Importance,
    RetrospectiveState,
    SourceAuthorizationStatus,
)
from app.services import retrospective, retrospective_ai, retrospective_query
from app.services.errors import ConcurrentUpdate, NotVisible, ResourceConflict, ValidationFailed
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def _case():
    uow = build_fake_uow()
    actor = Actor(user_id="analyst", teams=frozenset({"alpha"}))
    thesis = ThesisRecord(
        thesis_id="THS-RETRO-1",
        security_id="0175.HK",
        title="新能源周期验证",
        direction="观察",
        core_view="产品周期推动销量增长，但盈利仍需验证。",
        established_on=date(2025, 1, 1),
        owner=actor.user_id,
        visibility="团队",
        team="alpha",
    )
    uow.securities.add(SecurityRecord(thesis.security_id, "吉利汽车"))
    uow.thesis.add(thesis)
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-RETRO-1-H1",
            thesis_id=thesis.thesis_id,
            statement="新能源车型销量持续增长",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    uow.versions.add(
        VersionRecord(
            thesis_id=thesis.thesis_id,
            version=1,
            snapshot={"core_view": thesis.core_view},
            triggered_by="发布",
            created_by=actor.user_id,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    settings = Settings(_env_file=None, retrospective_center_enabled=True)
    return uow, actor, thesis, settings


def _create(uow, actor, thesis, settings):
    return retrospective.create(
        uow,
        thesis_id=thesis.thesis_id,
        retrospective_type="周期",
        title="2026 年中期逻辑复盘",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        data_cutoff_at=datetime(2026, 6, 30, 15, 59, tzinfo=UTC),
        actor=actor,
        settings=settings,
    )


def _publishable(record):
    content = dict(record.draft_content)
    content.update(
        {
            "summary": "区间内记录已完成复核。",
            "errors_and_omissions": "部分盈利数据尚未披露。",
            "limitations": "仅使用截止时点前的冻结来源。",
            "next_actions": "继续跟踪盈利与折扣率。",
        }
    )
    assessments = [dict(item) for item in content["hypothesis_assessments"]]
    assessments[0]["rationale"] = "截止时点证据仍不足。"
    content["hypothesis_assessments"] = assessments
    return content


def test_create_save_publish_and_revision_keep_immutable_versions() -> None:
    uow, actor, thesis, settings = _case()
    record = _create(uow, actor, thesis, settings)
    assert record.state == RetrospectiveState.DRAFT.value
    assert record.source_count == 1

    saved = retrospective.save_draft(
        uow,
        retrospective_id=record.retrospective_id,
        content=_publishable(record),
        expected_lock_version=record.lock_version,
        actor=actor,
    )
    with pytest.raises(ConcurrentUpdate):
        retrospective.save_draft(
            uow,
            retrospective_id=record.retrospective_id,
            content=_publishable(record),
            expected_lock_version=record.lock_version,
            actor=actor,
        )

    published = retrospective.publish(
        uow,
        retrospective_id=record.retrospective_id,
        publish_reason="完成首次人工复盘",
        expected_lock_version=saved.lock_version,
        actor=actor,
    )
    assert published.state == RetrospectiveState.PUBLISHED.value
    assert published.current_version == 1
    first = uow.retrospectives.get_version(record.retrospective_id, 1)
    assert first is not None
    assert first.content["summary"] == "区间内记录已完成复核。"

    revision = retrospective.start_revision(
        uow,
        retrospective_id=record.retrospective_id,
        reason="补充披露后的更正",
        expected_lock_version=published.lock_version,
        actor=actor,
    )
    owner_detail = retrospective_query.detail(
        uow, retrospective_id=record.retrospective_id, actor=actor
    )
    assert owner_detail.visible_content["revision_reason"] == "补充披露后的更正"
    team_detail = retrospective_query.detail(
        uow,
        retrospective_id=record.retrospective_id,
        actor=Actor(user_id="colleague", teams=frozenset({"alpha"})),
    )
    assert "revision_reason" not in team_detail.visible_content

    revised_content = dict(revision.draft_content)
    revised_content["summary"] = "更正后的区间复盘。"
    revised = retrospective.save_draft(
        uow,
        retrospective_id=record.retrospective_id,
        content=revised_content,
        expected_lock_version=revision.lock_version,
        actor=actor,
    )
    second_publish = retrospective.publish(
        uow,
        retrospective_id=record.retrospective_id,
        publish_reason="发布更正版本",
        expected_lock_version=revised.lock_version,
        actor=actor,
    )
    assert second_publish.current_version == 2
    assert "revision_reason" not in second_publish.draft_content
    assert retrospective_query.detail(
        uow, retrospective_id=record.retrospective_id, actor=actor
    ).allowed_actions == ("view", "export", "revise", "archive")
    assert uow.retrospectives.get_version(record.retrospective_id, 1) == first
    assert (
        uow.retrospectives.get_version(record.retrospective_id, 2).content["summary"]
        == "更正后的区间复盘。"
    )  # type: ignore[union-attr]
    archived = retrospective.archive(
        uow,
        retrospective_id=record.retrospective_id,
        reason="归档旧周期主报告",
        expected_lock_version=second_publish.lock_version,
        actor=actor,
    )
    replacement = _create(uow, actor, thesis, settings)
    assert archived.state == RetrospectiveState.ARCHIVED.value
    assert replacement.retrospective_id != record.retrospective_id


def test_source_preview_keeps_nearest_baseline_and_excludes_future_versions() -> None:
    uow, actor, thesis, settings = _case()
    uow.versions.add(
        VersionRecord(
            thesis_id=thesis.thesis_id,
            version=2,
            snapshot={"core_view": "区间内更新"},
            triggered_by="字段修改",
            created_by=actor.user_id,
            created_at=datetime(2026, 4, 15, tzinfo=UTC),
        )
    )
    uow.versions.add(
        VersionRecord(
            thesis_id=thesis.thesis_id,
            version=3,
            snapshot={"core_view": "未来更新"},
            triggered_by="字段修改",
            created_by=actor.user_id,
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
    )
    preview = retrospective.preview_sources(
        uow,
        thesis_id=thesis.thesis_id,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        data_cutoff_at=datetime(2026, 6, 30, 15, 59, tzinfo=UTC),
        actor=actor,
        settings=settings,
    )
    versions = [
        item.object_version for item in preview.sources if item.source_type == "thesis_version"
    ]
    assert versions == ["1", "2"]


def test_source_preview_uses_the_latest_authorized_revision_before_cutoff() -> None:
    uow, actor, thesis, settings = _case()
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-HISTORICAL",
            published_at=datetime(2026, 3, 1, tzinfo=UTC),
            content_hash="c" * 64,
            parser_version="parser-v1",
            title="历史公告",
            visibility_label="内部",
            content_status=DocumentContentStatus.FULL_TEXT.value,
            ingested_at=datetime(2026, 3, 2, tzinfo=UTC),
        ),
        [],
        [],
    )
    uow.assets.add_revision(
        DocumentRevisionRecord(
            revision_id="REV-BEFORE-CUTOFF",
            document_id="DOC-HISTORICAL",
            canonical_document_id="DOC-HISTORICAL",
            content_hash="d" * 64,
            source_filename="historical.pdf",
            object_key="documents/historical.pdf",
            authorization_status=SourceAuthorizationStatus.PUBLIC_DISCLOSURE_VERIFIED.value,
            created_at=datetime(2026, 3, 2, tzinfo=UTC),
        )
    )
    uow.assets.add_revision(
        DocumentRevisionRecord(
            revision_id="REV-AFTER-CUTOFF",
            document_id="DOC-HISTORICAL",
            canonical_document_id="DOC-HISTORICAL",
            content_hash="e" * 64,
            source_filename="future.pdf",
            object_key="documents/future.pdf",
            authorization_status=SourceAuthorizationStatus.PUBLIC_DISCLOSURE_VERIFIED.value,
            created_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
    )
    uow.evidence.add(
        EvidenceRecord(
            evidence_id="EVD-HISTORICAL",
            thesis_id=thesis.thesis_id,
            hypothesis_id="THS-RETRO-1-H1",
            evidence_type="事实",
            direction=ImpactDirection.SUPPORT,
            evidence_locator="page=1",
            source_document_id="DOC-HISTORICAL",
            source_document_title="历史公告",
            fact_excerpt="截止时点前已披露的事实",
            disclosed_at=datetime(2026, 3, 1, tzinfo=UTC),
            ingested_at=datetime(2026, 3, 2, tzinfo=UTC),
        )
    )
    uow.relations.add(
        EvidenceRelationRecord(
            relation_id="REL-HISTORICAL",
            evidence_id="EVD-HISTORICAL",
            thesis_id=thesis.thesis_id,
            hypothesis_id="THS-RETRO-1-H1",
            direction=ImpactDirection.SUPPORT,
            strength="高",
            status=ConfirmationStatus.CONFIRMED,
            created_by=actor.user_id,
            reviewed_by=actor.user_id,
            reviewed_at=datetime(2026, 3, 3, tzinfo=UTC),
        )
    )

    preview = retrospective.preview_sources(
        uow,
        thesis_id=thesis.thesis_id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        data_cutoff_at=datetime(2026, 6, 30, 15, 59, tzinfo=UTC),
        actor=actor,
        settings=settings,
    )
    evidence_source = next(
        item for item in preview.sources if item.source_type == "confirmed_evidence"
    )
    assert evidence_source.object_version == "REV-BEFORE-CUTOFF"
    assert evidence_source.content_hash == "d" * 64


def test_permissions_duplicate_and_publication_gate_are_server_side() -> None:
    uow, actor, thesis, settings = _case()
    record = _create(uow, actor, thesis, settings)
    with pytest.raises(ResourceConflict):
        _create(uow, actor, thesis, settings)
    with pytest.raises(NotVisible):
        retrospective_query.detail(
            uow,
            retrospective_id=record.retrospective_id,
            actor=Actor(user_id="outsider", teams=frozenset({"other"})),
        )
    with pytest.raises(ValidationFailed, match="复盘摘要"):
        retrospective.publish(
            uow,
            retrospective_id=record.retrospective_id,
            publish_reason="尝试越过门禁",
            expected_lock_version=record.lock_version,
            actor=actor,
        )


def test_confirmed_source_is_redacted_if_its_document_is_no_longer_visible() -> None:
    uow, actor, thesis, settings = _case()
    record = _create(uow, actor, thesis, settings)
    uow.retrospectives.add_sources(
        [
            RetrospectiveSourceRecord(
                source_id="RCS-REMOVED-DOCUMENT",
                retrospective_id=record.retrospective_id,
                source_type="confirmed_evidence",
                object_id="REL-REMOVED",
                locator="page=1",
                content_hash="b" * 64,
                summary="不应继续展示的原文摘要",
                metadata={"document_id": "DOC-REMOVED"},
            )
        ]
    )
    detail = retrospective_query.detail(uow, retrospective_id=record.retrospective_id, actor=actor)
    redacted = next(item for item in detail.sources if item.source_id == "RCS-REMOVED-DOCUMENT")
    assert redacted.locator is None
    assert redacted.content_hash is None
    assert redacted.summary == "来源当前不可打开或无访问权限"
    assert redacted.metadata == {"availability": "unavailable"}


def test_ai_candidate_uses_only_frozen_source_ids_and_does_not_overwrite_human_content() -> None:
    uow, actor, thesis, settings = _case()
    settings = settings.model_copy(
        update={"retrospective_ai_draft_enabled": True, "llm_provider": "local"}
    )
    record = _create(uow, actor, thesis, settings)
    original = dict(record.draft_content)
    result = retrospective_ai.generate(
        uow,
        retrospective_id=record.retrospective_id,
        expected_lock_version=record.lock_version,
        actor=actor,
        settings=settings,
    )
    assert result["status"] == "completed"
    stored = uow.retrospectives.get(record.retrospective_id)
    assert stored is not None
    assert stored.draft_content == original
    assert stored.ai_candidate is not None
    allowed = {item.source_id for item in uow.retrospectives.list_sources(record.retrospective_id)}
    assert set(stored.ai_candidate["citations"]) <= allowed
