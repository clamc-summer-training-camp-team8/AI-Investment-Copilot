"""初始投资逻辑草稿能力。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.ai.agents.evidence import EvidenceAgent
from app.ai.agents.types import EvidenceValidation, ThesisDraftRunResult
from app.ai.gateway import Gateway
from app.ai.retrieval import RetrievalDocument, RetrievalQuery, Retriever


class ThesisDraftAgent:
    """用观点和/或资料编排初始 Thesis 草稿；不写库、不发布正式 Thesis。"""

    def __init__(self, *, gateway: Gateway, retriever: Retriever) -> None:
        self.gateway = gateway
        self.retriever = retriever

    def generate(
        self,
        *,
        security_id: str,
        view: str = "",
        source_document_id: str | None = None,
        source_segments: list[RetrievalDocument] | None = None,
        investment_context: dict[str, Any] | None = None,
        industry_metrics: list[dict[str, Any]] | None = None,
        as_of: datetime | None = None,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 8,
    ) -> ThesisDraftRunResult:
        """先检索资料，再把带 locator 的片段传给 Gateway。"""
        if source_segments:
            self.retriever.add(source_segments)
        query_text = view or " ".join(document.content for document in (source_segments or []))
        retrieval = self.retriever.search(
            RetrievalQuery(
                text=query_text,
                security_id=security_id,
                as_of=as_of,
                allowed_visibility=allowed_visibility,
                top_k=top_k,
            )
        )
        segments = [(item.locator, item.content) for item in retrieval.items]
        if not segments and source_segments:
            segments = [(item.locator, item.content) for item in source_segments[:top_k]]

        def request_draft(repair_errors: list[str] | None = None):
            return self.gateway.thesis_draft(
                security_id=security_id,
                view=view,
                segments=segments,
                source_document_id=source_document_id,
                investment_context=investment_context,
                industry_metrics=industry_metrics,
                repair_errors=repair_errors,
            )

        outcome = request_draft()
        citation_check = EvidenceAgent.validate_thesis_citations(
            outcome.payload,
            allowed_locators={locator for locator, _ in segments},
        )
        if outcome.usable and not citation_check.valid:
            outcome = request_draft(_citation_repair_errors(citation_check))
        return ThesisDraftRunResult(
            security_id=security_id,
            retrieval=retrieval,
            outcome=outcome,
        )


def _citation_repair_errors(validation: EvidenceValidation) -> list[str]:
    missing = validation.missing_locators
    unsupported = validation.unsupported_claims
    errors: list[str] = []
    if missing:
        errors.append(f"引用不存在或不在输入资料中: {', '.join(missing)}")
    if unsupported:
        errors.append("保留 unsupported_claims，并删除没有资料支持的事实陈述")
    if not errors:
        errors.append("至少为输入资料支持的事实提供有效 locator 引用")
    return errors
