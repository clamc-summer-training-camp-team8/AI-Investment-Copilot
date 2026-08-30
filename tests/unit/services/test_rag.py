from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.core.domain import AssetSearchHitRecord
from app.services import assets
from app.services.errors import ValidationFailed
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def test_hybrid_retrieve_passes_permission_and_business_filters() -> None:
    uow = build_fake_uow()
    captured = {}
    published_at = datetime(2026, 8, 12, tzinfo=UTC)

    def search(**kwargs):
        captured.update(kwargs)
        return [
            AssetSearchHitRecord(
                document_id="DOC-1",
                locator="DOC-1#paragraph-1",
                content="正文",
                visibility_label="内部",
                rank=0.8,
                published_at=published_at,
                source="历史公告",
            )
        ]

    uow.assets.hybrid_search_segments = search  # type: ignore[method-assign]
    result = assets.hybrid_retrieve(
        uow,
        query="订单增长",
        actor=Actor(user_id="r1", document_labels=frozenset({"公开", "内部"})),
        settings=Settings(_env_file=None),
        security_ids=("600000",),
        industries=("医药",),
        published_to=datetime(2026, 8, 13, tzinfo=UTC),
        limit=5,
    )
    assert result[0].document_id == "DOC-1"
    assert result[0].published_at == published_at
    assert result[0].source == "历史公告"
    assert captured["visibility_labels"] == ("公开", "内部")
    assert captured["security_ids"] == ("600000",)
    assert captured["industries"] == ("医药",)
    assert len(captured["query_embedding"]) == 256


def test_hybrid_retrieve_rejects_reversed_time_window() -> None:
    with pytest.raises(ValidationFailed, match="published_from"):
        assets.hybrid_retrieve(
            build_fake_uow(),
            query="测试",
            actor=Actor(user_id="r1"),
            settings=Settings(_env_file=None),
            published_from=datetime(2026, 8, 14, tzinfo=UTC),
            published_to=datetime(2026, 8, 13, tzinfo=UTC),
        )
