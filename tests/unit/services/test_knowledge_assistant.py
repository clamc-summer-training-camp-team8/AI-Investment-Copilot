from datetime import UTC, datetime

import pytest

from app.ai.gateway import Gateway
from app.ai.providers.mock import MockProvider
from app.core.config import Settings
from app.core.domain import AssetSearchHitRecord, DocumentRecord, DocumentSegmentRecord
from app.services import knowledge_assistant
from app.services.errors import CitationInvalid
from app.services.permission import Actor
from tests.fakes import build_fake_uow


def _uow(content_status: str = "完整正文"):
    uow = build_fake_uow()
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-1",
            title="经营数据公告",
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
            content_hash="a" * 64,
            parser_version="v1",
            visibility_label="内部",
            content_status=content_status,
        ),
        [
            DocumentSegmentRecord(
                document_id="DOC-1",
                locator="DOC-1#paragraph-1",
                ordinal=1,
                content="公司月度销量同比增长 20%。",
                content_kind="paragraph" if content_status == "完整正文" else "title_index",
            )
        ],
        [],
    )
    uow.assets.hybrid_search_segments = lambda **_: [  # type: ignore[method-assign]
        AssetSearchHitRecord(
            document_id="DOC-1",
            locator="DOC-1#paragraph-1",
            content=(
                "公司月度销量同比增长 20%。"
                if content_status == "完整正文"
                else "公告标题（非正文）：月度销量公告"
            ),
            visibility_label="内部",
            rank=0.9,
            retrieval_mode="hybrid",
            source="经营数据公告",
            content_status=content_status,
            content_kind="paragraph" if content_status == "完整正文" else "title_index",
            published_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    ]
    return uow


def test_answer_uses_only_openable_full_text_citations() -> None:
    uow = _uow()
    result = knowledge_assistant.answer(
        uow,
        question="销量有什么变化？",
        actor=Actor(user_id="analyst"),
        settings=Settings(
            _env_file=None,
            knowledge_qa_enabled=True,
            knowledge_qa_graph_enabled=False,
        ),
    )
    assert result.answer_status == "supported"
    assert [item.locator for item in result.citations] == ["DOC-1#paragraph-1"]
    assert "20%" in result.answer
    assert "销量有什么变化" not in str([item.detail for item in uow.audit.items])


def test_title_index_returns_insufficient_without_model_call() -> None:
    uow = _uow("标题索引")
    result = knowledge_assistant.answer(
        uow,
        question="销量有什么变化？",
        actor=Actor(user_id="analyst"),
        settings=Settings(
            _env_file=None,
            knowledge_qa_enabled=True,
            knowledge_qa_graph_enabled=False,
        ),
    )
    assert result.answer_status == "insufficient_evidence"
    assert result.model_version == "not-invoked"
    assert result.citations == []
    assert all(item.action != "模型调用" for item in uow.audit.items)


def test_candidate_pool_outside_citation_is_rejected() -> None:
    uow = _uow()
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        knowledge_qa_enabled=True,
        knowledge_qa_graph_enabled=False,
    )
    provider = MockProvider(
        settings,
        answer_payload={
            "answer_status": "supported",
            "answer": "伪造回答 [S1]",
            "inferences": [],
            "citations": ["SECRET#paragraph-1"],
            "requires_human_review": True,
            "model_version": "mock",
            "prompt_version": "knowledge-answer-v1-grounded-citations",
            "generated_at": "2026-08-31T00:00:00Z",
            "ai_status": "候选",
        },
    )
    with pytest.raises(CitationInvalid):
        knowledge_assistant.answer(
            uow,
            question="销量有什么变化？",
            actor=Actor(user_id="analyst"),
            settings=settings,
            gateway=Gateway(provider=provider, settings=settings),
        )


def _uow_with_two_contexts():
    uow = _uow()
    uow.documents.add(
        DocumentRecord(
            document_id="DOC-2",
            title="毛利率公告",
            published_at=datetime(2026, 8, 2, tzinfo=UTC),
            content_hash="b" * 64,
            parser_version="v1",
            visibility_label="内部",
            content_status="完整正文",
        ),
        [
            DocumentSegmentRecord(
                document_id="DOC-2",
                locator="DOC-2#paragraph-2",
                ordinal=2,
                content="公司毛利率同比提升 2 个百分点。",
                content_kind="paragraph",
            )
        ],
        [],
    )
    first_hit = uow.assets.hybrid_search_segments()[0]
    second_hit = AssetSearchHitRecord(
        document_id="DOC-2",
        locator="DOC-2#paragraph-2",
        content="公司毛利率同比提升 2 个百分点。",
        visibility_label="内部",
        rank=0.8,
        retrieval_mode="hybrid",
        source="毛利率公告",
        content_status="完整正文",
        content_kind="paragraph",
        published_at=datetime(2026, 8, 2, tzinfo=UTC),
    )
    uow.assets.hybrid_search_segments = lambda **_: [first_hit, second_hit]  # type: ignore[method-assign]
    return uow


def _second_context_provider(settings: Settings, answer: str) -> MockProvider:
    return MockProvider(
        settings,
        answer_payload={
            "answer_status": "supported",
            "answer": answer,
            "inferences": [],
            "citations": ["DOC-2#paragraph-2"],
            "requires_human_review": True,
            "model_version": "mock",
            "prompt_version": "knowledge-answer-v1-grounded-citations",
            "generated_at": "2026-08-31T00:00:00Z",
            "ai_status": "候选",
        },
    )


def test_citation_keeps_server_assigned_context_number() -> None:
    uow = _uow_with_two_contexts()
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        knowledge_qa_enabled=True,
        knowledge_qa_graph_enabled=False,
    )
    provider = _second_context_provider(settings, "毛利率同比提升 [S2]")
    result = knowledge_assistant.answer(
        uow,
        question="毛利率有什么变化？",
        actor=Actor(user_id="analyst"),
        settings=settings,
        gateway=Gateway(provider=provider, settings=settings),
    )
    assert [(item.ref, item.locator) for item in result.citations] == [("S2", "DOC-2#paragraph-2")]


def test_answer_reference_number_must_match_citation_locator() -> None:
    uow = _uow_with_two_contexts()
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        knowledge_qa_enabled=True,
        knowledge_qa_graph_enabled=False,
    )
    provider = _second_context_provider(settings, "毛利率同比提升 [S1]")
    with pytest.raises(CitationInvalid, match="引用编号"):
        knowledge_assistant.answer(
            uow,
            question="毛利率有什么变化？",
            actor=Actor(user_id="analyst"),
            settings=settings,
            gateway=Gateway(provider=provider, settings=settings),
        )
