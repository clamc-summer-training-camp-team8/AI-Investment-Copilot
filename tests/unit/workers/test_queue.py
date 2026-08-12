from __future__ import annotations

import pytest

from app.services.permission import Actor
from app.workers.queue import enqueue_document


class FakeRedis:
    def __init__(self) -> None:
        self.enqueued: tuple[str, dict[str, object], str] | None = None
        self.owner: tuple[str, str] | None = None

    async def enqueue_job(
        self, function: str, payload: dict[str, object], *, _job_id: str
    ) -> object:
        self.enqueued = (function, payload, _job_id)
        return object()

    async def set(self, key: str, value: str, **kwargs: object) -> None:
        self.owner = (key, value)


@pytest.mark.asyncio
async def test_enqueue_document_records_owner_and_uses_stable_job_id() -> None:
    redis = FakeRedis()

    job_id = await enqueue_document(  # type: ignore[arg-type]
        redis,
        document_id="DOC-1",
        path="C:/storage/DOC-1.txt",
        actor=Actor(user_id="researcher-1", teams=frozenset({"team-a"})),
    )

    assert job_id == "document-DOC-1"
    assert redis.enqueued is not None
    assert redis.enqueued[0] == "process_document_job"
    assert redis.enqueued[1]["job_id"] == "document-DOC-1"
    assert redis.enqueued[1]["actor_id"] == "researcher-1"
    assert redis.owner == ("job-owner:document-DOC-1", "researcher-1")
