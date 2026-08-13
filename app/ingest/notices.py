"""公告详情页采集与标准化。

输入是公告列表中的标题、日期和详情 URL，输出是可缓存、可解析并能回到原文的
`ParsedDocument`。该模块不调用模型、不写业务数据库，也不依赖 `app.ai`。
"""

from __future__ import annotations

import hashlib
import html as html_lib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final
from urllib.parse import urljoin

import httpx

from app.core.timeutil import BUSINESS_TZ, ensure_aware
from app.ingest.parsers.base import ParsedDocument, ParseError, RawSegment

NOTICE_PARSER_VERSION: Final = "notice-html-v1"
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(
    r"<(?:p|div|section|article|br|tr|li|h[1-6])\b[^>]*>|</(?:p|div|section|article|tr|li|h[1-6])>",
    re.I,
)
_NON_CONTENT_RE = re.compile(
    r"<(?:head|script|style|noscript|nav|footer)\b[^>]*>.*?</(?:head|script|style|noscript|nav|footer)>",
    re.I | re.S,
)
_PDF_RE = re.compile(r"https?://[^\\x22\\x27\\s<>]+?\\.pdf(?:\\?[^\\x22\\x27\\s<>]*)?", re.I)


@dataclass(frozen=True)
class NoticeRecord:
    """公告列表中的最小记录。"""

    security_id: str
    security_name: str
    title: str
    notice_date: str
    detail_url: str

    @property
    def document_id(self) -> str:
        digest = hashlib.sha256(self.detail_url.encode("utf-8")).hexdigest()[:16]
        return f"notice-{self.security_id}-{digest}"

    @property
    def published_at(self) -> datetime:
        try:
            value = datetime.strptime(self.notice_date[:10], "%Y-%m-%d")
        except ValueError as exc:
            raise ParseError(f"公告日期无法解析: {self.notice_date!r}") from exc
        return ensure_aware(value, assume=BUSINESS_TZ)


@dataclass(frozen=True)
class FetchedNotice:
    record: NoticeRecord
    raw_path: Path
    source_url: str
    parsed: ParsedDocument
    content_type: str


def _clean_text(value: str) -> str:
    value = html_lib.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _html_segments(source: str) -> list[str]:
    """提取 HTML 块文本，排除脚本、样式和空导航碎片。"""
    cleaned = _NON_CONTENT_RE.sub(" ", source)
    blocks = _BLOCK_RE.sub("\n", cleaned)
    text = _TAG_RE.sub(" ", blocks)
    paragraphs = [_clean_text(line) for line in text.splitlines()]
    return [p for p in paragraphs if len(p) >= 2]


def parse_notice_html(
    source: str,
    *,
    title: str,
    published_at: datetime,
    doc_type: str = "公告",
) -> ParsedDocument:
    """将公告详情 HTML 转成段落级 `ParsedDocument`。"""
    segments = _html_segments(source)
    if not segments:
        raise ParseError("公告 HTML 未提取到正文")
    return ParsedDocument(
        title=title,
        segments=[RawSegment(ordinal=i, content=p) for i, p in enumerate(segments, start=1)],
        published_at=published_at,
        doc_type=doc_type,
        parser_version=NOTICE_PARSER_VERSION,
    )


def _pdf_url(source: str, base_url: str) -> str | None:
    match = _PDF_RE.search(html_lib.unescape(source))
    return urljoin(base_url, match.group(0)) if match else None


class NoticeFetcher:
    """抓取并缓存公告正文，支持注入 httpx Client 以便离线测试。"""

    def __init__(
        self,
        cache_dir: Path,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.raw_dir = cache_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "AI-Investment-Copilot/0.1"},
            follow_redirects=True,
        )

    def _get(self, url: str) -> httpx.Response:
        response = self.client.get(url)
        response.raise_for_status()
        return response

    def fetch(self, record: NoticeRecord) -> FetchedNotice:
        response = self._get(record.detail_url)
        content_type = response.headers.get("content-type", "").lower()
        source_url = str(response.url)

        if "application/pdf" in content_type or response.content[:4] == b"%PDF":
            raw_path = self.raw_dir / f"{record.document_id}.pdf"
            raw_path.write_bytes(response.content)
            from app.ingest.parsers.text import parse_pdf

            parsed = parse_pdf(raw_path)
            parsed = ParsedDocument(
                title=record.title,
                segments=parsed.segments,
                published_at=record.published_at,
                doc_type="公告",
                parser_version=f"{NOTICE_PARSER_VERSION}+pdf",
                warnings=parsed.warnings,
            )
            return FetchedNotice(record, raw_path, source_url, parsed, content_type)

        source = response.text
        raw_path = self.raw_dir / f"{record.document_id}.html"
        raw_path.write_text(source, encoding="utf-8")
        pdf_url = _pdf_url(source, source_url)
        if pdf_url:
            pdf_response = self._get(pdf_url)
            if pdf_response.content[:4] == b"%PDF":
                pdf_path = self.raw_dir / f"{record.document_id}.pdf"
                pdf_path.write_bytes(pdf_response.content)
                from app.ingest.parsers.text import parse_pdf

                parsed_pdf = parse_pdf(pdf_path)
                parsed = ParsedDocument(
                    title=record.title,
                    segments=parsed_pdf.segments,
                    published_at=record.published_at,
                    doc_type="公告",
                    parser_version=f"{NOTICE_PARSER_VERSION}+pdf",
                    warnings=parsed_pdf.warnings,
                )
                return FetchedNotice(record, pdf_path, pdf_url, parsed, "application/pdf")

        parsed = parse_notice_html(
            source,
            title=record.title,
            published_at=record.published_at,
        )
        return FetchedNotice(record, raw_path, source_url, parsed, content_type)
