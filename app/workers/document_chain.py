"""文档处理链（PRD 7.1）。

```
ingest.parse → ingest.segment → ingest.fingerprint
  → ai.extract_thesis_draft → contracts 校验 → services.thesis.save_draft
```

**这条链止于草稿。** 任何情况下不发布、不生成正式证据、不改状态——人工闸门在
`app/services`，worker 只负责把候选结果准备好（workers/README.md）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.ai.gateway import Gateway
from app.ai.errors import ModelUnavailable
from app.ai.retrieval import RetrievalDocument
from app.ai.runtime import InvestmentResearchAgent
from app.core.enums import AiStatus, Severity
from app.ingest.parsers.base import ParsedDocument, ParseError
from app.ingest.parsers.text import parse_file
from app.ingest.segmentation import Segment, content_hash, segment_document
from app.services import audit
from app.services.permission import Actor
from app.services.ports import UnitOfWork


@dataclass
class DocumentResult:
    """处理结果。失败时也返回，不抛异常给上层——原文件必须保留（PRD 7.4）。"""

    document_id: str
    ok: bool
    segments: list[Segment]
    content_hash: str | None = None
    parser_version: str | None = None
    published_at: datetime | None = None
    failure_reason: str | None = None
    quality_issues: list[tuple[str, Severity, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.quality_issues is None:
            self.quality_issues = []


def check_quality(parsed: ParsedDocument) -> list[tuple[str, Severity, str]]:
    """入库前的数据质量检查。

    DQ-001 是阻断级：`published_at` 为空则进隔离区，禁止生成正式信号，且
    **不允许用入库时间兜底**——用入库时间填充会直接造成未来信息泄露。
    """
    issues: list[tuple[str, Severity, str]] = []
    if parsed.published_at is None:
        issues.append(
            (
                "DQ-001",
                Severity.BLOCKING,
                "首次公开时间为空，进入隔离区。请人工补录，不允许用入库时间兜底",
            )
        )
    if not parsed.segments:
        issues.append(("DQ-001", Severity.BLOCKING, "未解析出任何段落"))
    return issues


def is_blocked(issues: list[tuple[str, Severity, str]]) -> bool:
    return any(sev is Severity.BLOCKING for _, sev, _ in issues)


def process_document(
    *,
    document_id: str,
    path: Path,
    published_at: datetime | None = None,
) -> DocumentResult:
    """解析并切片。解析失败返回失败结果，保留原因，不删除原文件。"""
    try:
        parsed = parse_file(path)
    except ParseError as exc:
        return DocumentResult(
            document_id=document_id,
            ok=False,
            segments=[],
            failure_reason=exc.reason,
        )

    if parsed.published_at is None and published_at is not None:
        parsed = ParsedDocument(
            title=parsed.title,
            segments=parsed.segments,
            published_at=published_at,
            doc_type=parsed.doc_type,
            parser_version=parsed.parser_version,
            warnings=parsed.warnings,
        )

    issues = check_quality(parsed)
    segments = segment_document(document_id, parsed)

    return DocumentResult(
        document_id=document_id,
        ok=not is_blocked(issues),
        segments=segments,
        content_hash=content_hash(parsed.body),
        parser_version=parsed.parser_version,
        published_at=parsed.published_at,
        failure_reason=None if not is_blocked(issues) else issues[0][2],
        quality_issues=issues,
    )


def draft_from_document(
    uow: UnitOfWork,
    ai: Gateway | InvestmentResearchAgent,
    *,
    thesis_id: str,
    security_id: str,
    view: str,
    result: DocumentResult,
    actor: Actor,
) -> dict[str, object] | None:
    """调模型生成卡片草稿并落库。

    返回 None 表示进人工队列：解析失败或质量阻断时不生成草稿，因为草稿会带上
    引用，而引用指向的是不该进入检索范围的数据。
    """
    if not result.ok:
        return None

    from app.services import thesis as thesis_service

    if result.published_at is None:
        return None
    runtime = (
        ai
        if isinstance(ai, InvestmentResearchAgent)
        else InvestmentResearchAgent.build(ai)
    )
    execution = runtime.draft_thesis(
        security_id=security_id,
        view=view,
        source_document_id=result.document_id,
        source_segments=[
            RetrievalDocument(
                document_id=result.document_id,
                security_id=security_id,
                locator=segment.locator,
                content=segment.content,
                published_at=result.published_at,
            )
            for segment in result.segments
        ],
        as_of=result.published_at,
        idempotency_key=f"document:{result.document_id}:thesis:{thesis_id}",
    )
    if execution.retryable:
        raise ModelUnavailable(
            execution.degraded_reason or "Runtime 暂时不可用",
            retryable=True,
        )
    if execution.result is None:
        return None
    outcome = execution.result.outcome

    audit.record_model_call(
        uow.audit,
        actor=actor.user_id,
        object_type="document",
        object_id=result.document_id,
        model_version=str(outcome.payload.get("model_version", "")),
        prompt_version=str(outcome.payload.get("prompt_version", "")),
        ai_status=outcome.ai_status.value,
    )

    if outcome.ai_status is AiStatus.PARSE_FAILED:
        return None

    thesis_service.create_draft(uow, thesis_id=thesis_id, draft=outcome.payload, actor=actor)
    return outcome.payload
