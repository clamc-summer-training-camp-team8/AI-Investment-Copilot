"""基于权限可见知识片段的问答编排。"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.ai.gateway import Gateway
from app.ai.prompts.templates import KNOWLEDGE_ANSWER
from app.ai.retrieval import KeywordRetriever, RetrievalDocument, RetrievalQuery
from app.core.config import Settings
from app.core.domain import (
    AssetSearchHitRecord,
    DocumentSegmentRecord,
    SecurityRecord,
    ThesisQuery,
    ThesisRecord,
    UnitOfWork,
)
from app.core.enums import AiStatus
from app.core.timeutil import now
from app.services import assets, audit, graph_rag, permission, status
from app.services.errors import CitationInvalid, NotVisible, ValidationFailed
from app.services.permission import Actor

_LOCATOR = re.compile(r"^[A-Za-z0-9_.-]+#paragraph-[0-9]+$")
_USABLE_CONTENT = frozenset({"完整正文", "合成样例"})
_REPORT_TITLE = re.compile(r"(?:年度报告|半年度报告|季度报告)")
_REPORT_NOISE = re.compile(r"(?:摘要|审计报告|说明会|取消审核|问询回复)")
_FINANCIAL_CUES = frozenset(
    {
        "营收",
        "营业收入",
        "收入",
        "净利润",
        "利润",
        "毛利率",
        "现金流",
        "财务",
        "业绩",
        "销量",
        "交付量",
    }
)
_THESIS_CUES = frozenset({"投资逻辑", "核心观点", "核心假设", "研究逻辑"})
_STATUS_CUES = frozenset({"失效", "状态", "验证中", "待验证", "重大风险", "已关闭"})


@dataclass(frozen=True)
class _Scope:
    thesis_id: str | None
    security_id: str | None
    security_name: str | None
    origin: str


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


def _intent(question: str) -> str:
    if any(cue in question for cue in _THESIS_CUES) and any(
        cue in question for cue in _STATUS_CUES
    ):
        return "thesis_status"
    if any(cue in question for cue in _THESIS_CUES):
        return "thesis"
    if any(cue in question for cue in _FINANCIAL_CUES):
        return "financial"
    return "general"


def _security_terms(record: SecurityRecord) -> tuple[str, ...]:
    values = {
        record.security_id.strip(),
        record.name.strip(),
        (record.ticker or "").strip(),
        *(alias.strip() for alias in record.aliases),
    }
    return tuple(sorted((value for value in values if len(value) >= 2), key=len, reverse=True))


def _infer_security(
    uow: UnitOfWork,
    *,
    question: str,
    history: list[dict[str, str]],
) -> SecurityRecord | None:
    securities = uow.securities.search(limit=100)
    sources = [question, *reversed([item["content"] for item in history if item["role"] == "user"])]
    for source in sources:
        normalized = source.casefold()
        matches: list[tuple[int, SecurityRecord]] = []
        for security in securities:
            matched = max(
                (len(term) for term in _security_terms(security) if term.casefold() in normalized),
                default=0,
            )
            if matched:
                matches.append((matched, security))
        if not matches:
            continue
        matches.sort(key=lambda item: (-item[0], item[1].security_id))
        best_length = matches[0][0]
        best = {item.security_id: item for length, item in matches if length == best_length}
        if len(best) == 1:
            return next(iter(best.values()))
    return None


def _visible_thesis(actor: Actor, thesis: ThesisRecord | None) -> ThesisRecord | None:
    if thesis is None or not permission.can_view_thesis(
        actor,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    ):
        return None
    return thesis


def _resolve_scope(
    uow: UnitOfWork,
    *,
    actor: Actor,
    question: str,
    history: list[dict[str, str]],
    thesis_id: str | None,
    security_id: str | None,
    as_of: datetime,
) -> _Scope:
    explicit_thesis_id, explicit_security_id = _require_context(
        uow,
        actor=actor,
        thesis_id=thesis_id,
        security_id=security_id,
    )
    security = uow.securities.get(explicit_security_id) if explicit_security_id else None
    origin = "explicit" if explicit_security_id or explicit_thesis_id else "global"
    if security is None and explicit_security_id is None:
        security = _infer_security(uow, question=question, history=history)
        if security is not None:
            explicit_security_id = security.security_id
            origin = (
                "question"
                if security.name in question or security.security_id in question
                else "history"
            )

    resolved_thesis_id = explicit_thesis_id
    if resolved_thesis_id is None and explicit_security_id:
        current = _visible_thesis(actor, uow.thesis.get_by_security(explicit_security_id))
        if current is not None and current.established_on <= as_of.date():
            resolved_thesis_id = current.thesis_id
            origin = f"{origin}+current_thesis"

    if security is None and explicit_security_id:
        security = uow.securities.get(explicit_security_id)
    return _Scope(
        thesis_id=resolved_thesis_id,
        security_id=explicit_security_id,
        security_name=security.name if security else None,
        origin=origin,
    )


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _structured_thesis_context(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    security_name: str | None,
    settings: Settings,
    as_of: datetime,
) -> _Context | None:
    thesis = uow.thesis.get(thesis_id)
    if thesis is None:
        return None
    hypotheses = uow.thesis.list_hypotheses(thesis_id)
    relations = uow.relations.list_for_thesis(thesis_id)
    relation_counts = Counter(_status_value(item.status) for item in relations)
    suggestion = status.compute_suggestion(
        uow,
        thesis=thesis,
        hypotheses=hypotheses,
        thresholds=settings.rules,
        today=as_of.date(),
    )
    hypothesis_lines = [
        (
            f"- {item.name or item.hypothesis_id}：{item.statement}；"
            f"正式状态={item.status}；失效条件={item.invalidation_rule or '未配置'}"
        )
        for item in hypotheses
    ]
    content = "\n".join(
        [
            f"结构化研究记录（截止 {as_of.date().isoformat()}，不是模型推断）",
            f"证券：{security_name or thesis.security_id}（{thesis.security_id}）",
            f"当前投资逻辑：{thesis.title}（{thesis.thesis_id}）",
            f"正式状态：{thesis.status.value}；当前版本：v{thesis.version}；是否当前版本：{thesis.is_current}",
            f"核心观点：{thesis.core_view}",
            (
                "规则引擎只读复算建议："
                f"{suggestion.suggested_status.value}；理由：{'；'.join(suggestion.reasons)}。"
                "该建议不等于正式状态变更，仍需研究员确认。"
            ),
            (
                "证据关系状态："
                f"已确认 {relation_counts.get('已确认', 0)} 条，"
                f"待确认 {relation_counts.get('待确认', 0)} 条，"
                f"已拒绝/停用 {relation_counts.get('已拒绝', 0) + relation_counts.get('已停用', 0)} 条。"
            ),
            "关键假设：",
            *hypothesis_lines,
        ]
    )
    return _Context(
        locator=f"{thesis.thesis_id}#paragraph-1",
        document_id=thesis.thesis_id,
        title=thesis.title,
        content=content,
        published_at=datetime.combine(thesis.established_on, datetime.min.time(), tzinfo=UTC),
        content_status="结构化研究数据",
        content_kind="structured_thesis",
        retrieval_mode="structured+rules",
    )


def _portfolio_status_context(
    uow: UnitOfWork,
    *,
    actor: Actor,
    settings: Settings,
    as_of: datetime,
) -> _Context | None:
    theses, _ = uow.thesis.search(ThesisQuery(limit=100))
    visible = [
        item
        for item in theses
        if item.established_on <= as_of.date() and _visible_thesis(actor, item) is not None
    ]
    if not visible:
        return None
    lines = [f"当前投资逻辑状态清单（截止 {as_of.date().isoformat()}，不是模型推断）"]
    for thesis in visible:
        hypotheses = uow.thesis.list_hypotheses(thesis.thesis_id)
        suggestion = status.compute_suggestion(
            uow,
            thesis=thesis,
            hypotheses=hypotheses,
            thresholds=settings.rules,
            today=as_of.date(),
        )
        lines.append(
            f"- {thesis.security_id}｜{thesis.title}｜正式状态={thesis.status.value}｜"
            f"规则建议={suggestion.suggested_status.value}｜理由={'；'.join(suggestion.reasons)}"
        )
    return _Context(
        locator="THESIS-PORTFOLIO#paragraph-1",
        document_id="THESIS-PORTFOLIO",
        title="当前投资逻辑状态清单",
        content="\n".join(lines),
        published_at=as_of,
        content_status="结构化研究数据",
        content_kind="structured_portfolio",
        retrieval_mode="structured+rules",
    )


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


def _financial_terms(question: str) -> tuple[str, ...]:
    terms: list[str] = []
    if "营收" in question or "收入" in question or "业绩" in question:
        terms.extend(("营业收入", "营业总收入", "主要会计数据和财务指标"))
    if "净利润" in question or "利润" in question or "业绩" in question:
        terms.extend(("归属于上市公司股东的净利润", "净利润"))
    if "毛利率" in question:
        terms.extend(("毛利率", "营业成本"))
    if "现金流" in question:
        terms.extend(("经营活动产生的现金流量净额", "现金流"))
    if "销量" in question or "交付量" in question:
        terms.extend(("新能源汽车销量", "销量", "交付量"))
    if not terms:
        terms.extend(
            (
                "主要会计数据和财务指标",
                "营业收入",
                "归属于上市公司股东的净利润",
                "新能源汽车销量",
            )
        )
    return tuple(dict.fromkeys(terms))


def _financial_contexts(
    uow: UnitOfWork,
    *,
    question: str,
    security_id: str,
    actor: Actor,
    as_of: datetime,
    limit: int = 4,
) -> list[_Context]:
    documents, _ = assets.list_document_catalog(
        uow,
        actor=actor,
        content_status="完整正文",
        security_id=security_id,
        published_to=as_of,
        sort="published_at",
        direction="desc",
        limit=100,
    )
    reports = [
        item
        for item in documents
        if _REPORT_TITLE.search(item.title) and not _REPORT_NOISE.search(item.title)
    ][:4]
    terms = _financial_terms(question)
    contexts: list[_Context] = []
    for document_rank, document in enumerate(reports):
        scored: list[tuple[float, DocumentSegmentRecord]] = []
        for segment in uow.documents.list_segments(document.document_id):
            if segment.content_kind == "title_index" or len(segment.content.strip()) < 20:
                continue
            matches = sum(term in segment.content for term in terms)
            if not matches:
                continue
            score = float(matches * 4 - document_rank)
            if "主要会计数据和财务指标" in segment.content:
                score += 5
            if "本报告期比上年同期" in segment.content or "本年比上年增减" in segment.content:
                score += 3
            if 80 <= len(segment.content) <= 3000:
                score += 1
            scored.append((score, segment))
        scored.sort(key=lambda item: (-item[0], item[1].ordinal))
        # 财务总结优先覆盖多个报告期；同一报告的相邻表格片段容易挤占上下文，
        # 且通常重复“主要财务数据”中的数值。
        for _, segment in scored[:1]:
            contexts.append(
                _Context(
                    locator=segment.locator,
                    document_id=document.document_id,
                    title=document.title,
                    content=segment.content[:3000],
                    published_at=document.published_at,
                    content_status=document.content_status,
                    content_kind=segment.content_kind,
                    retrieval_mode="financial-report",
                )
            )
            if len(contexts) >= limit:
                return contexts
    return contexts


def _retrieval_query(
    question: str,
    *,
    intent: str,
    scope: _Scope,
    as_of: datetime,
) -> str:
    company = scope.security_name or scope.security_id or ""
    if intent == "financial":
        terms = " ".join(_financial_terms(question))
        return f"{company} {as_of.year} {as_of.year - 1} {terms}".strip()
    if intent == "general" and company:
        return f"{company} 最新 主要会计数据和财务指标 营业收入 净利润 " "新能源汽车销量 经营情况"
    if intent in {"thesis", "thesis_status"} and company:
        return f"{company} 核心观点 关键假设 营业收入 毛利率 销量 海外业务"
    return question


def _rerank_hits(
    hits: list[AssetSearchHitRecord],
    *,
    question: str,
    intent: str,
    scope: _Scope,
    as_of: datetime,
) -> list[AssetSearchHitRecord]:
    terms = _financial_terms(question) if intent in {"financial", "general"} else ()

    def score(hit: AssetSearchHitRecord) -> tuple[float, str, str]:
        content = hit.content.strip()
        value = hit.rank
        if len(content) < 20:
            value -= 0.8
        if scope.security_name and content in {
            scope.security_name,
            f"对{scope.security_name}的重要性",
        }:
            value -= 1
        value += 0.18 * sum(term in content for term in terms)
        if intent in {"financial", "general"} and _REPORT_TITLE.search(hit.source):
            value += 0.15
        if hit.published_at:
            age_days = max(0, (as_of - hit.published_at).days)
            value += max(0.0, 0.12 * (1 - age_days / 1095))
        return (-value, hit.document_id, hit.locator)

    return sorted(hits, key=score)


def _extend_contexts(
    target: list[_Context],
    candidates: list[_Context],
    *,
    seen: set[str],
    per_document: dict[str, int],
    max_contexts: int,
    max_per_document: int = 2,
) -> None:
    for item in candidates:
        if item.locator in seen or per_document[item.document_id] >= max_per_document:
            continue
        seen.add(item.locator)
        per_document[item.document_id] += 1
        target.append(item)
        if len(target) >= max_contexts:
            return


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
    as_of = as_of or now()
    recent_history = (history or [])[-6:]
    answer_intent = _intent(normalized)
    scope = _resolve_scope(
        uow,
        actor=actor,
        question=normalized,
        history=recent_history,
        thesis_id=thesis_id,
        security_id=security_id,
        as_of=as_of,
    )
    request_id = f"QA-{uuid4().hex}"
    answer_id = f"ANS-{uuid4().hex}"

    structured_contexts: list[_Context] = []
    if scope.thesis_id:
        structured = _structured_thesis_context(
            uow,
            thesis_id=scope.thesis_id,
            security_name=scope.security_name,
            settings=settings,
            as_of=as_of,
        )
        if structured is not None:
            structured_contexts.append(structured)
    elif answer_intent == "thesis_status":
        portfolio = _portfolio_status_context(uow, actor=actor, settings=settings, as_of=as_of)
        if portfolio is not None:
            structured_contexts.append(portfolio)

    financial_contexts = (
        _financial_contexts(
            uow,
            question=normalized,
            security_id=scope.security_id,
            actor=actor,
            as_of=as_of,
        )
        if scope.security_id and answer_intent in {"financial", "general"}
        else []
    )
    skip_text_search = answer_intent == "thesis_status" and bool(structured_contexts)
    hits = (
        []
        if skip_text_search
        else assets.hybrid_retrieve(
            uow,
            query=_retrieval_query(
                normalized,
                intent=answer_intent,
                scope=scope,
                as_of=as_of,
            ),
            actor=actor,
            settings=settings,
            security_ids=(scope.security_id,) if scope.security_id else (),
            published_to=as_of,
            limit=60,
        )
    )
    hits = _rerank_hits(
        hits,
        question=normalized,
        intent=answer_intent,
        scope=scope,
        as_of=as_of,
    )

    graph_contexts: list[_Context] = []
    graph_snapshot_id: str | None = None
    retrieval_version = "intent-routed-hybrid-v2"
    if (
        scope.thesis_id
        and scope.security_id
        and settings.knowledge_qa_graph_enabled
        and answer_intent == "thesis"
    ):
        graph_contexts, graph_snapshot_id, graph_version = _graph_contexts(
            uow,
            question=normalized,
            thesis_id=scope.thesis_id,
            security_id=scope.security_id,
            actor=actor,
            as_of=as_of,
            settings=settings,
            text_hits=hits,
        )
        retrieval_version = f"intent-routed-hybrid-v2[{graph_version}]"

    text_contexts = [item for hit in hits if (item := _usable_hit(uow, hit)) is not None]
    deduped: list[_Context] = []
    seen: set[str] = set()
    per_document: dict[str, int] = defaultdict(int)
    ordered_groups = (
        [structured_contexts, graph_contexts, text_contexts]
        if answer_intent in {"thesis", "thesis_status"}
        else [financial_contexts, structured_contexts, text_contexts]
    )
    for group in ordered_groups:
        _extend_contexts(
            deduped,
            group,
            seen=seen,
            per_document=per_document,
            max_contexts=settings.knowledge_qa_max_contexts,
        )
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
                "intent": answer_intent,
                "security_id": scope.security_id,
                "thesis_id": scope.thesis_id,
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
            "intent": answer_intent,
            "scope_origin": scope.origin,
            "thesis_id": scope.thesis_id,
            "security_id": scope.security_id,
            "security_name": scope.security_name,
            "as_of": as_of.isoformat(),
        },
        history=recent_history,
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
            "intent": answer_intent,
            "scope_origin": scope.origin,
            "security_id": scope.security_id,
            "thesis_id": scope.thesis_id,
            "structured_contexts": len(structured_contexts),
            "financial_contexts": len(financial_contexts),
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
