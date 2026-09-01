from datetime import UTC, date, datetime

from app.core.config import Settings
from app.core.domain import AssetSearchHitRecord, EventRecord, SecurityRecord, ThesisRecord
from app.core.enums import ThesisStatus
from app.services import global_search
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def test_global_search_groups_real_objects_and_does_not_audit_query_text() -> None:
    uow = build_fake_uow()
    uow.securities.add(
        SecurityRecord(
            security_id="0175.HK",
            name="吉利汽车",
            ticker="0175",
            industry="新能源汽车",
            aliases=["Geely"],
        )
    )
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-GEELY",
            security_id="0175.HK",
            title="新能源产品周期",
            direction="看多",
            core_view="产品周期支持销量增长",
            established_on=date(2026, 1, 1),
            owner="analyst",
            status=ThesisStatus.VALIDATING,
            visibility="团队",
            team="research",
        )
    )
    uow.events.add(
        EventRecord(
            event_id="EVT-1",
            document_id="DOC-1",
            security_id="0175.HK",
            event_type="业绩",
            summary="吉利汽车销量增长",
            disclosure_time=datetime(2026, 8, 1, tzinfo=UTC),
            fingerprint="evt-1",
        )
    )
    uow.assets.hybrid_search_segments = lambda **_: [  # type: ignore[method-assign]
        AssetSearchHitRecord(
            document_id="DOC-1",
            locator="DOC-1#paragraph-1",
            content="吉利汽车月度销量增长。",
            visibility_label="内部",
            rank=0.9,
            retrieval_mode="hybrid",
            source="月度销量公告",
            content_status="完整正文",
        )
    ]

    result = global_search.search(
        uow,
        query="吉利",
        actor=Actor(user_id="analyst", teams=frozenset({"research"})),
        settings=Settings(_env_file=None),
        types=("security", "thesis", "event", "document"),
    )

    groups = {group.type: group.items for group in result.groups}
    assert groups["security"][0].target == global_search.SearchTarget("thesis", "THS-GEELY")
    assert groups["thesis"][0].id == "THS-GEELY"
    assert groups["event"][0].id == "EVT-1"
    assert groups["document"][0].content_status == "完整正文"
    audit_detail = uow.audit.items[-1].detail or {}
    assert "吉利" not in str(audit_detail)
    assert audit_detail["query_length"] == 2


def test_security_search_matches_alias_and_industry() -> None:
    uow = build_fake_uow()
    uow.securities.add(
        SecurityRecord(
            security_id="0175.HK",
            name="吉利汽车",
            industry="新能源汽车",
            aliases=["Geely"],
        )
    )
    assert uow.securities.search("Geely")[0].security_id == "0175.HK"
    assert uow.securities.search("新能源")[0].security_id == "0175.HK"


def test_preserved_title_segment_is_still_labeled_as_non_body_metadata() -> None:
    item = global_search._document_search_item(
        AssetSearchHitRecord(
            document_id="DOC-1",
            locator="DOC-1#paragraph-1",
            content="公告标题：月度销量公告",
            visibility_label="公开",
            rank=0.8,
            source="月度销量公告",
            content_status="完整正文",
            content_kind="title_index",
        )
    )

    assert item.content_status == "标题索引"
    assert item.content_kind == "title_index"
    assert item.subtitle == "标题索引"
