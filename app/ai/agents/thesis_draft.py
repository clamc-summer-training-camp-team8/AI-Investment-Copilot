"""初始投资逻辑草稿能力。"""

from __future__ import annotations

from datetime import datetime

from app.ai.agents.types import ThesisDraftRunResult
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
        as_of: datetime | None = None,
        allowed_visibility: frozenset[str] = frozenset({"公开"}),
        top_k: int = 8,
    ) -> ThesisDraftRunResult:
        """先检索资料，再把带 locator 的片段传给 Gateway。"""
        if source_segments:
            self.retriever.add(source_segments)
        query_text = view or " ".join(
            document.content for document in (source_segments or [])
        )
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
        outcome = self.gateway.thesis_draft(
            security_id=security_id,
            view=view,
            segments=segments,
            source_document_id=source_document_id,
        )
        return ThesisDraftRunResult(
            security_id=security_id,
            retrieval=retrieval,
            outcome=outcome,
        )
