"""基于权限可见知识片段的问答编排。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.ai.gateway import Gateway
from app.ai.prompts.templates import KNOWLEDGE_ANSWER
from app.ai.retrieval import KeywordRetriever, RetrievalDocument, RetrievalQuery
from app.core.config import Settings
from app.core.domain import AssetSearchHitRecord, UnitOfWork
from app.core.enums import AiStatus
from app.core.timeutil import now
from app.services import assets, audit, graph_rag, permission
from app.services.errors import CitationInvalid, NotVisible, ValidationFailed
from app.services.permission import Actor

_LOCATOR = re.compile(r"^[A-Za-z0-9_.-]+#paragraph-[0-9]+$")
_USABLE_CONTENT = frozenset({"完整正文", "合成样例"})


@dataclass(frozen=True)
class AnswerCitation:
    ref: str
    locator: str
    document_id: str
    title: str
    excerpt: str
    published_at: datetime | None
    content_status: str
    content_kind: str
    retrieval_mode: str


@dataclass(frozen=True)
class KnowledgeAnswer:
    answer_id: str
    answer_status: str
    ai_status: str
    answer: str
    inferences: list[str]
    citations: list[AnswerCitation]
    model_version: str
    prompt_version: str
    retrieval_version: str
    graph_snapshot_id: str | None
    generated_at: datetime
    request_id: str


@dataclass(frozen=True)
class _Context:
    locator: str
    document_id: str
    title: str
    content: str
    published_at: datetime | None
    content_status: str
    content_kind: str
    retrieval_mode: str

    def provider_payload(self, index: int) -> dict[str, Any]:
        return {
            "ref": f"S{index}",
            "locator": self.locator,
            "document_id": self.document_id,
            "source": self.title,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "content_status": self.content_status,
            "content_kind": self.content_kind,
            "content": self.content,
        }


def _require_context(
    uow: UnitOfWork,
    *,
    actor: Actor,
    thesis_id: str | None,
    security_id: str | None,
) -> tuple[str | None, str | None]:
    normalized_security = security_id.strip().upper() if security_id else None
    if thesis_id:
        thesis = uow.thesis.get(thesis_id)
        if thesis is None:
            raise NotVisible("研究上下文不存在或无访问权限")
        permission.ensure_thesis_visible(
            actor,
            thesis_id=thesis.thesis_id,
            owner=thesis.owner,
            visibility=thesis.visibility,
            team=thesis.team,
        )
        if normalized_security and normalized_security != thesis.security_id:
            raise NotVisible("研究上下文不存在或无访问权限")
        return thesis.thesis_id, thesis.security_id
    if normalized_security and uow.securities.get(normalized_security) is None:
        raise NotVisible("研究上下文不存在或无访问权限")
    return None, normalized_security


def _usable_hit(uow: UnitOfWork, hit: AssetSearchHitRecord) -> _Context | None:
    if not _LOCATOR.fullmatch(hit.locator) or not hit.locator.startswith(f"{hit.document_id}#"):
        return None
    document = uow.documents.get(hit.document_id)
    if (
        document is None
        or document.deleted_at is not None
        or document.content_status not in _USABLE_CONTENT
        or hit.content_kind == "title_index"
        or hit.content.startswith("公告标题（非正文）")
    ):
        return None
    return _Context(
        locator=hit.locator,
        document_id=hit.document_id,
        title=hit.source or document.title or hit.document_id,
        content=hit.content,
        published_at=hit.published_at or document.published_at,
        content_status=document.content_status,
        content_kind=hit.content_kind,
        retrieval_mode=hit.retrieval_mode,
    )


def _graph_contexts(
    uow: UnitOfWork,
    *,
    question: str,
    thesis_id: str,
    security_id: str,
    actor: Actor,
    as_of: datetime | None,
    settings: Settings,
    text_hits: list[AssetSearchHitRecord],
) -> tuple[list[_Context], str | None, str]:
    corpus = graph_rag.build_graph_rag_corpus(
        uow, thesis_ids=[thesis_id], include_pending=False, as_of=as_of
    )
    base = KeywordRetriever()
    base.add(
        [
            RetrievalDocument(
                document_id=hit.document_id,
                security_id=security_id,
                locator=hit.locator,
                content=hit.content,
                published_at=hit.published_at or as_of or now(),
                visibility_label=hit.visibility_label,
                source=hit.source or hit.document_id,
            )
            for hit in text_hits
            if _LOCATOR.fullmatch(hit.locator)
        ]
    )
    retriever = graph_rag.build_graph_retriever_from_corpus(
        corpus,
        text_retriever=base,
        text_weight=settings.rag_graph_text_weight,
        graph_weight=settings.rag_graph_relation_weight,
        max_hops=settings.rag_graph_max_hops,
        assist_only=settings.rag_graph_assist_only,
    )
    result = retriever.search(
        RetrievalQuery(
            text=question,
            security_id=security_id,
            as_of=as_of,
            allowed_visibility=actor.document_labels,
            top_k=min(12, settings.knowledge_qa_max_contexts * 2),
            seed_node_ids=frozenset({f"thesis:{thesis_id}"}),
        )
    )
    contexts: list[_Context] = []
    for item in result.items:
        if not _LOCATOR.fullmatch(item.locator) or not item.locator.startswith(
            f"{item.document_id}#"
        ):
            continue
        document = uow.documents.get(item.document_id)
        if (
            document is None
            or document.deleted_at is not None
            or document.content_status not in _USABLE_CONTENT
        ):
            continue
        segment = next(
            (
                row
                for row in uow.documents.list_segments(item.document_id)
                if row.locator == item.locator
            ),
            None,
        )
        if segment and segment.content_kind == "title_index":
            continue
        contexts.append(
            _Context(
                locator=item.locator,
                document_id=item.document_id,
                title=item.source or document.title or item.document_id,
                content=item.content,
                published_at=item.published_at,
                content_status=document.content_status,
                content_kind=segment.content_kind if segment else "paragraph",
                retrieval_mode="text+graph",
            )
        )
    return contexts, corpus.snapshot.snapshot_id, result.retrieval_version


def answer(
    uow: UnitOfWork,
    *,
    question: str,
    actor: Actor,
    settings: Settings,
    thesis_id: str | None = None,
    security_id: str | None = None,
    as_of: datetime | None = None,
    history: list[dict[str, str]] | None = None,
    gateway: Gateway | None = None,
) -> KnowledgeAnswer:
    normalized = question.strip()
    if len(normalized) < 2:
        raise ValidationFailed("问题至少需要 2 个字符")
    thesis_id, security_id = _require_context(
        uow,
        actor=actor,
        thesis_id=thesis_id,
        security_id=security_id,
    )
    as_of = as_of or now()
    request_id = f"QA-{uuid4().hex}"
    answer_id = f"ANS-{uuid4().hex}"
    hits = assets.hybrid_retrieve(
        uow,
        query=normalized,
        actor=actor,
        settings=settings,
        security_ids=(security_id,) if security_id else (),
        published_to=as_of,
        limit=20,
    )

    contexts: list[_Context] = []
    graph_snapshot_id: str | None = None
    retrieval_version = "hybrid-search-v1"
    if thesis_id and security_id and settings.knowledge_qa_graph_enabled:
        contexts, graph_snapshot_id, retrieval_version = _graph_contexts(
            uow,
            question=normalized,
            thesis_id=thesis_id,
            security_id=security_id,
            actor=actor,
            as_of=as_of,
            settings=settings,
            text_hits=hits,
        )
    contexts.extend(filter(None, (_usable_hit(uow, hit) for hit in hits)))
    deduped: list[_Context] = []
    seen: set[str] = set()
    for item in contexts:
        if item.locator in seen:
            continue
        seen.add(item.locator)
        deduped.append(item)
        if len(deduped) >= settings.knowledge_qa_max_contexts:
            break

    if not deduped:
        audit.record(
            uow.audit,
            actor=actor.user_id,
            action="知识问答证据不足",
            object_type="knowledge_answer",
            object_id=answer_id,
            detail={
                "request_id": request_id,
                "question_length": len(normalized),
                "retrieved_candidates": len(hits),
                "usable_contexts": 0,
            },
        )
        generated_at = now()
        return KnowledgeAnswer(
            answer_id=answer_id,
            answer_status="insufficient_evidence",
            ai_status=AiStatus.CANDIDATE.value,
            answer=(
                "当前知识库没有可用于核验该问题的完整正文。"
                "命中资料可能仍处于标题索引状态，请缩小公司范围或先完成正文解析。"
            ),
            inferences=[],
            citations=[],
            model_version="not-invoked",
            prompt_version=KNOWLEDGE_ANSWER.version,
            retrieval_version=retrieval_version,
            graph_snapshot_id=graph_snapshot_id,
            generated_at=generated_at,
            request_id=request_id,
        )

    provider_contexts = [
        item.provider_payload(index) for index, item in enumerate(deduped, start=1)
    ]
    gateway = gateway or Gateway.build(settings)
    outcome = gateway.knowledge_answer(
        question=normalized,
        context={
            "thesis_id": thesis_id,
            "security_id": security_id,
            "as_of": as_of.isoformat(),
        },
        history=(history or [])[-6:],
        contexts=provider_contexts,
    )
    if not outcome.usable:
        raise ValidationFailed("模型回答未通过知识问答契约校验")
    raw_citations = outcome.payload.get("citations")
    cited = [str(item) for item in raw_citations] if isinstance(raw_citations, list) else []
    allowed = {item.locator: item for item in deduped}
    allowed_refs = {item.locator: f"S{index}" for index, item in enumerate(deduped, start=1)}
    if any(locator not in allowed for locator in cited):
        raise CitationInvalid("模型返回了不属于本轮可见候选的引用")
    answer_status = str(outcome.payload.get("answer_status") or "insufficient_evidence")
    answer_text = str(outcome.payload["answer"])
    if answer_status in {"supported", "partial"} and not cited:
        raise CitationInvalid("事实回答缺少可核验引用")
    if answer_status in {"supported", "partial"}:
        cited_refs = {allowed_refs[locator] for locator in cited}
        answer_refs = {f"S{item}" for item in re.findall(r"\[S([1-9][0-9]*)\]", answer_text)}
        if answer_refs != cited_refs:
            raise CitationInvalid("回答正文的引用编号与引用列表不一致")
    citation_outputs = [
        AnswerCitation(
            ref=allowed_refs[locator],
            locator=locator,
            document_id=allowed[locator].document_id,
            title=allowed[locator].title,
            excerpt=allowed[locator].content[:360],
            published_at=allowed[locator].published_at,
            content_status=allowed[locator].content_status,
            content_kind=allowed[locator].content_kind,
            retrieval_mode=allowed[locator].retrieval_mode,
        )
        for locator in dict.fromkeys(cited)
    ]
    audit.record_model_call(
        uow.audit,
        actor=actor.user_id,
        object_type="knowledge_answer",
        object_id=answer_id,
        model_version=str(outcome.payload.get("model_version") or gateway.provider.model_version),
        prompt_version=str(outcome.payload.get("prompt_version") or KNOWLEDGE_ANSWER.version),
        ai_status=outcome.ai_status.value,
        model_metadata={
            "provider": settings.llm_provider,
        },
    )
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="知识问答完成",
        object_type="knowledge_answer",
        object_id=answer_id,
        detail={
            "request_id": request_id,
            "question_length": len(normalized),
            "retrieved_candidates": len(hits),
            "usable_contexts": len(deduped),
            "citation_count": len(citation_outputs),
            "answer_status": answer_status,
            "retrieval_version": retrieval_version,
            "graph_snapshot_id": graph_snapshot_id,
        },
    )
    generated = datetime.fromisoformat(str(outcome.payload["generated_at"]).replace("Z", "+00:00"))
    return KnowledgeAnswer(
        answer_id=answer_id,
        answer_status=answer_status,
        ai_status=outcome.ai_status.value,
        answer=answer_text,
        inferences=[str(item) for item in outcome.payload.get("inferences", [])],
        citations=citation_outputs,
        model_version=str(outcome.payload["model_version"]),
        prompt_version=str(outcome.payload["prompt_version"]),
        retrieval_version=retrieval_version,
        graph_snapshot_id=graph_snapshot_id,
        generated_at=generated,
        request_id=request_id,
    )


def record_feedback(
    uow: UnitOfWork,
    *,
    answer_id: str,
    value: str,
    reason: str | None,
    actor: Actor,
) -> None:
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="知识问答反馈",
        object_type="knowledge_answer",
        object_id=answer_id,
        detail={"value": value, "reason": reason},
    )
