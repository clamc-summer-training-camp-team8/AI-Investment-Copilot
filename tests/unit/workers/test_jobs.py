from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from arq import Retry

from app.ai.errors import ModelUnavailable
from app.core.config import Settings
from app.workers import jobs
from app.workers.document_chain import DocumentResult
from tests.fakes import build_fake_uow


def _payload(path: Path) -> dict[str, object]:
    return {
        "document_id": "DOC-1",
        "path": str(path),
        "published_at": "2026-08-11T09:00:00+08:00",
        "actor_id": "researcher-1",
        "actor_teams": ["team-a"],
    }


@pytest.mark.asyncio
async def test_document_job_runs_real_text_parse_without_model(tmp_path: Path, monkeypatch) -> None:
    conf = Settings(_env_file=None, storage_dir=tmp_path)
    upload = tmp_path / "uploads" / "DOC-1.txt"
    upload.parent.mkdir()
    upload.write_text("公告标题\n\n公司披露经营数据。", encoding="utf-8")
    monkeypatch.setattr(jobs, "Settings", lambda: conf)
    uow = build_fake_uow()

    @contextmanager
    def fake_uow_scope():
        yield uow

    monkeypatch.setattr(jobs, "uow_scope", fake_uow_scope)

    result = await jobs.process_document_job({}, _payload(upload))

    assert result["ok"] is True
    assert result["segment_count"] == 2
    assert result["draft_created"] is False
    assert result["content_hash"]
    assert result["persisted_document_id"] == "DOC-1"
    assert result["fact_count"] == 0
    assert len(uow.documents.list_segments("DOC-1")) == 2


@pytest.mark.asyncio
async def test_document_job_retries_model_then_degrades_to_review(
    tmp_path: Path, monkeypatch
) -> None:
    conf = Settings(_env_file=None, storage_dir=tmp_path)
    upload = tmp_path / "uploads" / "DOC-1.txt"
    upload.parent.mkdir()
    upload.write_text("正文", encoding="utf-8")
    payload = _payload(upload) | {
        "thesis_id": "THS-1",
        "security_id": "600000.SH",
        "view": "订单增长",
    }
    parsed = DocumentResult(
        document_id="DOC-1",
        ok=True,
        segments=[],
        content_hash="abc",
        parser_version="v1",
        published_at=datetime.fromisoformat("2026-08-11T09:00:00+08:00"),
    )
    reviews: list[dict[str, object]] = []

    @contextmanager
    def fake_uow_scope():
        yield build_fake_uow()

    def fail_draft(*args: object, **kwargs: object) -> None:
        raise ModelUnavailable("endpoint timeout", retryable=True)

    monkeypatch.setattr(jobs, "Settings", lambda: conf)
    monkeypatch.setattr(jobs, "process_document", lambda **kwargs: parsed)
    monkeypatch.setattr(jobs.Gateway, "build", lambda settings: object())
    monkeypatch.setattr(jobs, "uow_scope", fake_uow_scope)
    monkeypatch.setattr(jobs, "draft_from_document", fail_draft)
    monkeypatch.setattr(jobs, "_create_failure_review", lambda **kwargs: reviews.append(kwargs))

    with pytest.raises(Retry):
        await jobs.process_document_job({"job_try": 1, "max_tries": 3}, payload)

    result = await jobs.process_document_job({"job_try": 3, "max_tries": 3}, payload)

    assert result == {
        "ok": False,
        "document_id": "DOC-1",
        "reason": "endpoint timeout",
        "manual_review": True,
    }
    assert reviews[0]["thesis_id"] == "THS-1"
    assert reviews[0]["document_id"] == "DOC-1"
