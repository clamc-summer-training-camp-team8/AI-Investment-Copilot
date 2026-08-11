"""后端任务输入到 AI Runtime 类型的轻量适配。

后端 worker 保留自己的领域对象；本模块只读取字段，不 import `app.db`、
`app.services` 或具体 ORM。这样 integrated 分支可以逐步从 `Gateway` 切换到
`InvestmentResearchAgent`，而旧的 Gateway 调用仍然兼容。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any

from app.ai.agents import AgentEvent, CandidateHypothesis, InvestmentLogicChangeAgent, ThesisDraftAgent
from app.ai.gateway import Gateway
from app.ai.retrieval import KeywordRetriever, RetrievalDocument, Retriever
from app.ai.runtime import InvestmentResearchAgent, RuntimeExecution

_MISSING = object()


def _read(value: object, *names: str, default: Any = _MISSING) -> Any:
    """同时支持 integrated worker 的 dataclass 和后端 JSON 字典。"""
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    if default is not _MISSING:
        return default
    raise ValueError(f"后端 AI 输入缺少字段: {names[0]}")


def _text(value: object, *names: str, default: str | None = None) -> str | None:
    raw = _read(value, *names, default=default)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or default


def _datetime(value: object, *, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value.strip():
        try:
            result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} 不是有效 ISO 时间: {value!r}") from exc
    else:
        raise ValueError(f"后端 AI 输入缺少字段: {field}")
    # 后端当前使用带时区时间；对旧 JSON 的 naive 时间统一按 UTC 解释，
    # 避免在 Retriever 的 as_of 过滤中出现 aware/naive 比较异常。
    return result if result.tzinfo is not None else result.replace(tzinfo=timezone.utc)


def _date(value: object, *, field: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError as exc:
            raise ValueError(f"{field} 不是有效 ISO 日期: {value!r}") from exc
    raise ValueError(f"{field} 不是有效日期")


def to_agent_event(
    event: object,
    *,
    security_id: str,
    segment_locator: str | None = None,
) -> AgentEvent:
    """把 integrated 的 `ExtractedEvent` 或等价 JSON 转成 `AgentEvent`。"""
    locator = segment_locator or _text(event, "evidence_locator", "segment_locator")
    if not locator:
        raise ValueError("事件缺少 evidence_locator，不能进入 AI 证据链")
    document_id = _text(event, "document_id")
    event_id = _text(event, "event_id")
    segment_text = _text(event, "summary", "segment_text", "evidence")
    if not document_id or not event_id or not segment_text:
        raise ValueError("事件必须包含 event_id、document_id 和 summary")
    return AgentEvent(
        event_id=event_id,
        document_id=document_id,
        security_id=security_id,
        segment_locator=locator,
        segment_text=segment_text,
        disclosure_time=_datetime(_read(event, "disclosure_time"), field="disclosure_time"),
        event_type=_text(event, "event_type", default="其他") or "其他",
        occurred_on=_date(_read(event, "occurred_on", default=None), field="occurred_on"),
    )


def to_candidate_hypotheses(hypotheses: Iterable[object]) -> list[CandidateHypothesis]:
    """把后端 HypothesisRecord 或 JSON 列表转成 AI 候选假设。"""
    result: list[CandidateHypothesis] = []
    for hypothesis in hypotheses:
        thesis_id = _text(hypothesis, "thesis_id")
        hypothesis_id = _text(hypothesis, "hypothesis_id")
        statement = _text(hypothesis, "statement", "content")
        if not thesis_id or not hypothesis_id or not statement:
            raise ValueError("候选假设必须包含 thesis_id、hypothesis_id 和 statement")
        result.append(CandidateHypothesis(thesis_id, hypothesis_id, statement))
    return result


def build_runtime(gateway: Gateway, retriever: Retriever | None = None) -> InvestmentResearchAgent:
    """用后端已构造的 Gateway 创建统一 Runtime。

    未注入 Retriever 时使用关键词基线，生产环境应传入后端构造的混合 Retriever。
    """
    active_retriever = retriever or KeywordRetriever()
    return InvestmentResearchAgent(
        thesis_draft=ThesisDraftAgent(gateway=gateway, retriever=active_retriever),
        logic_change=InvestmentLogicChangeAgent(gateway=gateway, retriever=active_retriever),
    )


def analyze_backend_event(
    runtime: InvestmentResearchAgent,
    *,
    event: object,
    hypotheses: Iterable[object],
    security_id: str,
    segment_locator: str | None = None,
    allowed_visibility: frozenset[str] = frozenset({"公开"}),
    top_k: int = 3,
) -> RuntimeExecution:
    """供 integrated `change_chain` 调用的事件分析入口。"""
    return runtime.analyze_event(
        to_agent_event(event, security_id=security_id, segment_locator=segment_locator),
        to_candidate_hypotheses(hypotheses),
        allowed_visibility=allowed_visibility,
        top_k=top_k,
    )


def draft_backend_document(
    runtime: InvestmentResearchAgent,
    *,
    security_id: str,
    view: str = "",
    document_id: str | None = None,
    segments: Iterable[object] = (),
    published_at: datetime | str | None = None,
    visibility_label: str = "公开",
    source: str = "backend",
    as_of: datetime | None = None,
    top_k: int = 8,
) -> RuntimeExecution:
    """供 integrated 文档 worker 调用的 Thesis 草稿入口。"""
    raw_segments = list(segments)
    documents: list[RetrievalDocument] = []
    if raw_segments and published_at is None:
        raise ValueError("带正文切片生成 Thesis 草稿时必须提供 published_at")
    published = _datetime(published_at, field="published_at") if published_at is not None else None
    if raw_segments:
        assert published is not None
    for segment in raw_segments:
        segment_document_id = _text(segment, "document_id", default=document_id)
        locator = _text(segment, "locator", "segment_locator")
        content = _text(segment, "content", "text")
        if not segment_document_id or not locator or not content:
            raise ValueError("文档切片必须包含 document_id、locator 和 content")
        documents.append(
            RetrievalDocument(
                document_id=segment_document_id,
                security_id=security_id,
                locator=locator,
                content=content,
                published_at=published,
                visibility_label=visibility_label,
                source=source,
            )
        )
    return runtime.draft_thesis(
        security_id=security_id,
        view=view,
        source_document_id=document_id,
        source_segments=documents,
        as_of=as_of,
        allowed_visibility=frozenset({visibility_label}),
        top_k=top_k,
    )
