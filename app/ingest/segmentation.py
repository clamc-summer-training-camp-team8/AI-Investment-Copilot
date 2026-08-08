"""切片、指纹与引用定位。

`evidence_locator` 的精度决定产品可信度上限：研究员点开引用发现对不上，就不会
再信任任何 AI 输出（ingest/README.md）。因此 locator 格式固定、可解析、可回查。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from app.ingest.parsers.base import ParsedDocument, RawSegment

LOCATOR_PATTERN = re.compile(r"^(?P<document_id>[A-Za-z0-9_.-]+)#paragraph-(?P<ordinal>\d+)$")


@dataclass(frozen=True)
class Segment:
    """入库用的切片。locator 是证据定位的唯一凭据。"""

    document_id: str
    locator: str
    ordinal: int
    content: str
    page: int | None = None


def build_locator(document_id: str, ordinal: int) -> str:
    return f"{document_id}#paragraph-{ordinal}"


def parse_locator(locator: str) -> tuple[str, int]:
    """解析 locator。格式不合法直接抛错，不做宽松兜底。

    宽松解析会让错误的 locator 悄悄存进证据链，等到研究员点开才发现对不上。
    """
    matched = LOCATOR_PATTERN.match(locator)
    if matched is None:
        raise ValueError(f"证据定位格式非法: {locator!r}，应为 {{document_id}}#paragraph-{{n}}")
    return matched.group("document_id"), int(matched.group("ordinal"))


def content_hash(text: str) -> str:
    """SHA-256 内容指纹（FLD-003）。用于文档去重与版本追踪。

    先归一空白再哈希：同一内容多渠道转载常有空白差异，不归一会让 DQ-002 的去重
    形同虚设。
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    return sha256(normalized.encode("utf-8")).hexdigest()


def event_fingerprint(*parts: str) -> str:
    """事件指纹。同一事实多源转载时合并为同一事件（FR-R-005）。"""
    normalized = "|".join(re.sub(r"\s+", " ", p).strip() for p in parts if p)
    return sha256(normalized.encode("utf-8")).hexdigest()


def segment_document(document_id: str, parsed: ParsedDocument) -> list[Segment]:
    """把解析结果转为可入库的切片。

    切片粒度就是段落，与 locator 一一对应。切得更碎会丢语义，切得更粗定位没用；
    切片规则变化算 parser_version 变更（ingest/README.md）。
    """
    return [
        Segment(
            document_id=document_id,
            locator=build_locator(document_id, seg.ordinal),
            ordinal=seg.ordinal,
            content=seg.content,
            page=seg.page,
        )
        for seg in parsed.segments
    ]


def dedupe_segments(segments: list[Segment]) -> list[Segment]:
    """同文档内的重复段落去重，保留首次出现的 locator。"""
    seen: set[str] = set()
    kept: list[Segment] = []
    for seg in segments:
        digest = content_hash(seg.content)
        if digest in seen:
            continue
        seen.add(digest)
        kept.append(seg)
    return kept


def find_segment(segments: list[Segment], locator: str) -> Segment | None:
    """按 locator 回查段落。契约测试用它验证「引用必须能打开原文」。"""
    for seg in segments:
        if seg.locator == locator:
            return seg
    return None


def raw_segments_from_texts(texts: list[str]) -> list[RawSegment]:
    """测试与脚本用的便捷构造。"""
    return [RawSegment(ordinal=i, content=t) for i, t in enumerate(texts, start=1)]
