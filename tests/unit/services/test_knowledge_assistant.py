from datetime import UTC, date, datetime

import pytest

from app.ai.gateway import Gateway
from app.ai.providers.mock import MockProvider
from app.core.config import Settings
from app.core.domain import (
    AssetDocumentRecord,
    AssetSearchHitRecord,
    DocumentRecord,
    DocumentSegmentRecord,
    HypothesisRecord,
    SecurityRecord,
    ThesisRecord,
)
from app.core.enums import Importance, ThesisStatus
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
        question="公司有什么变化？",
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
            question="公司有什么变化？",
            actor=Actor(user_id="analyst"),
            settings=settings,
            gateway=Gateway(provider=provider, settings=settings),
        )


def _byd_uow():
    uow = build_fake_uow()
    uow.securities.add(
        SecurityRecord(
            security_id="002594",
            name="比亚迪",
            ticker="002594",
            industry="新能源汽车",
        )
    )
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-002594-2026Q1",
            security_id="002594",
            title="比亚迪2026Q1观察：整车与动力电池",
            direction="观察",
            core_view="销量和海外业务支撑收入，需跟踪毛利率。",
            established_on=date(2026, 1, 20),
            owner="analyst",
            status=ThesisStatus.VALIDATING,
            version=3,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="THS-002594-2026Q1-H1",
            thesis_id="THS-002594-2026Q1",
            statement="新能源汽车销量支撑收入增长",
            hypothesis_type="经营",
            importance=Importance.CORE,
            name="需求与出货",
            invalidation_rule="营业收入同比连续两个季度转负则失效",
        )
    )
    return uow


def _answer_provider(settings: Settings, *, locator: str, answer: str) -> MockProvider:
    return MockProvider(
        settings,
        answer_payload={
            "answer_status": "supported",
            "answer": answer,
            "inferences": [],
            "citations": [locator],
            "requires_human_review": True,
            "model_version": "mock",
            "prompt_version": "knowledge-answer-v2-intent-routed-grounding",
            "generated_at": "2026-09-01T00:00:00Z",
            "ai_status": "候选",
        },
    )


def test_company_and_current_thesis_are_inferred_from_history_for_status_question() -> None:
    uow = _byd_uow()
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        knowledge_qa_enabled=True,
        knowledge_qa_graph_enabled=False,
    )
    locator = "THS-002594-2026Q1#paragraph-1"
    result = knowledge_assistant.answer(
        uow,
        question="当前是否存在失效状态的投资逻辑？",
        history=[{"role": "user", "content": "总结比亚迪当前的投资逻辑"}],
        actor=Actor(user_id="analyst"),
        settings=settings,
        gateway=Gateway(
            provider=_answer_provider(
                settings,
                locator=locator,
                answer="当前正式状态为验证中，规则建议不等于正式状态 [S1]",
            ),
            settings=settings,
        ),
    )
    assert [(item.locator, item.content_kind) for item in result.citations] == [
        (locator, "structured_thesis")
    ]
    completion = next(item for item in uow.audit.items if item.action == "知识问答完成")
    assert completion.detail["security_id"] == "002594"
    assert completion.detail["scope_origin"] == "history+current_thesis"
    assert completion.detail["retrieved_candidates"] == 0


def test_financial_intent_prefers_latest_report_key_data_over_short_name_hits() -> None:
    uow = _byd_uow()
    published_at = datetime(2026, 4, 29, tzinfo=UTC)
    document_id = "DOC-EVT-002594-00375"
    locator = f"{document_id}#paragraph-3"
    segment = DocumentSegmentRecord(
        document_id=document_id,
        locator=locator,
        ordinal=3,
        content=(
            "2026年第一季度主要会计数据和财务指标：营业收入（元）"
            "150,225,314,000.00，上年同期170,360,448,000.00，"
            "本报告期比上年同期减少11.82%。"
        ),
        content_kind="paragraph",
    )
    uow.documents.add(
        DocumentRecord(
            document_id=document_id,
            title="2026年一季度报告",
            published_at=published_at,
            content_hash="c" * 64,
            parser_version="v1",
            visibility_label="内部",
            content_status="完整正文",
        ),
        [segment],
        [],
    )
    uow.assets.catalog_documents[document_id] = AssetDocumentRecord(
        document_id=document_id,
        title="2026年一季度报告",
        source_id=None,
        source_name="巨潮资讯",
        doc_type="定期报告",
        published_at=published_at,
        ingested_at=published_at,
        content_status="完整正文",
        visibility_label="内部",
        is_illustrative=False,
        deleted_at=None,
        archived=True,
        authorization_status="公开披露已核验",
        revision_count=1,
        segment_count=1,
        latest_run_status="succeeded",
        latest_run_at=published_at,
        security_ids=("002594",),
        security_names=("比亚迪",),
        industries=("新能源汽车",),
    )
    uow.assets.hybrid_search_segments = lambda **_: [  # type: ignore[method-assign]
        AssetSearchHitRecord(
            document_id=document_id,
            locator=locator,
            content=segment.content,
            visibility_label="内部",
            rank=0.1,
            source="2026年一季度报告",
            content_status="完整正文",
            content_kind="paragraph",
            published_at=published_at,
        )
    ]
    settings = Settings(
        _env_file=None,
        llm_provider="mock",
        knowledge_qa_enabled=True,
        knowledge_qa_graph_enabled=False,
    )
    result = knowledge_assistant.answer(
        uow,
        question="总结比亚迪最近的营收情况",
        actor=Actor(user_id="analyst"),
        settings=settings,
        gateway=Gateway(
            provider=_answer_provider(
                settings,
                locator=locator,
                answer="2026年一季度营业收入同比下降11.82% [S1]",
            ),
            settings=settings,
        ),
    )
    assert result.answer_status == "supported"
    assert [(item.locator, item.retrieval_mode) for item in result.citations] == [
        (locator, "financial-report")
    ]
