from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.core.domain import DocumentProcessingJobRecord, SecurityRecord
from app.services import ingestion
from app.services.errors import ValidationFailed
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def test_security_suggestions_match_name_ticker_and_alias() -> None:
    uow = build_fake_uow()
    uow.securities.add(
        SecurityRecord(
            security_id="600519.SH",
            name="贵州茅台",
            ticker="600519",
            aliases=["茅台"],
        )
    )

    candidates = ingestion.suggest_securities(
        uow,
        title="贵州茅台年度报告",
        segments=[("DOC-1#paragraph-1", "茅台披露营业收入同比增长。")],
    )

    assert candidates[0]["security_id"] == "600519.SH"
    assert "贵州茅台" in candidates[0]["matched_terms"]


def test_dead_letter_replay_gets_new_job_id_and_keeps_source(tmp_path: Path) -> None:
    path = tmp_path / "uploads" / "DOC-1.txt"
    path.parent.mkdir()
    path.write_text("正文", encoding="utf-8")
    uow = build_fake_uow()
    source = DocumentProcessingJobRecord(
        job_id="document-DOC-1",
        document_id="DOC-1",
        owner="researcher-1",
        upload_path=str(path),
        source_filename="report.txt",
        published_at=datetime.fromisoformat("2026-08-11T09:00:00+08:00"),
        status="dead_letter",
        attempt_count=3,
    )
    uow.processing_jobs.add(source)

    replay = ingestion.build_replay(uow, source=source, actor=Actor(user_id="researcher-1"))

    assert replay.job_id != source.job_id
    assert replay.attempt_count == 4
    assert replay.upload_path == source.upload_path
    assert replay.status == "queued"


def test_successful_job_is_not_replayable(tmp_path: Path) -> None:
    path = tmp_path / "DOC-1.txt"
    path.write_text("正文", encoding="utf-8")
    source = DocumentProcessingJobRecord(
        job_id="document-DOC-1",
        document_id="DOC-1",
        owner="researcher-1",
        upload_path=str(path),
        source_filename="report.txt",
        published_at=None,
        status="succeeded",
    )

    with pytest.raises(ValidationFailed):
        ingestion.build_replay(build_fake_uow(), source=source, actor=Actor(user_id="researcher-1"))


def test_job_lifecycle_tracks_current_attempt() -> None:
    uow = build_fake_uow()
    uow.processing_jobs.add(
        DocumentProcessingJobRecord(
            job_id="document-DOC-1",
            document_id="DOC-1",
            owner="researcher-1",
            upload_path="C:/storage/DOC-1.txt",
            source_filename="report.txt",
            published_at=None,
        )
    )

    ingestion.mark_running(uow, "document-DOC-1", attempt_count=2)
    running = uow.processing_jobs.get("document-DOC-1")
    assert running is not None
    assert running.status == "running"
    assert running.attempt_count == 2

    ingestion.mark_retrying(uow, "document-DOC-1", reason="temporary failure", attempt_count=2)
    retrying = uow.processing_jobs.get("document-DOC-1")
    assert retrying is not None
    assert retrying.status == "retrying"
    assert retrying.attempt_count == 2
