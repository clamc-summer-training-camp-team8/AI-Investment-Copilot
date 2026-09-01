"""东方财富资料适配器。

适配器只负责网络读取和字段标准化，不直接写业务表。调用方可将返回的
``EastmoneyDocument`` 转交现有 ``document_chain``，从而复用去重、分段、事实
抽取和 Graph RAG 入库流程。
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import Any, ClassVar
from urllib.parse import urljoin

import httpx


@dataclass(frozen=True)
class EastmoneyDocument:
    security_id: str
    category: str
    title: str
    published_at: datetime | None
    source: str | None
    body: str
    source_url: str
    attachment_url: str | None = None
    author: str | None = None
    rating: str | None = None
    institution: str | None = None
    analyst: str | None = None
    interactions: dict[str, int] | None = None

    @property
    def content_hash(self) -> str:
        value = f"{self.security_id}|{self.category}|{self.title}|{self.published_at}|{self.body}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


class EastmoneyAdapter:
    """按栏目调用东方财富接口的通用适配器。

    endpoint_templates 可以由部署配置提供，避免把某家公司或某个接口写死在
    代码中。模板必须包含 ``{security_id}``，值为返回 JSON 的 URL。
    """

    DEFAULT_TEMPLATES: ClassVar[dict[str, str]] = {
        "news": "https://guba.eastmoney.com/list,{security_id},f.html",
        "announcements": "https://data.eastmoney.com/notices/stock/{security_id}.html",
        "research_reports": "https://data.eastmoney.com/report/stock.jshtml?quote={security_id}",
        "post": "",
    }

    def __init__(
        self,
        *,
        endpoint_templates: dict[str, str] | None = None,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.endpoint_templates = self.DEFAULT_TEMPLATES | (endpoint_templates or {})
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def fetch_news(self, security_id: str) -> list[EastmoneyDocument]:
        return self._fetch_category(security_id, "news", "资讯")

    def fetch_announcements(self, security_id: str) -> list[EastmoneyDocument]:
        return self._fetch_category(security_id, "announcements", "公告")

    def fetch_research_reports(self, security_id: str) -> list[EastmoneyDocument]:
        return self._fetch_category(security_id, "research_reports", "研报")

    def fetch_post(self, security_id: str) -> list[EastmoneyDocument]:
        return self._fetch_category(security_id, "post", "帖子")

    def parse_attachment(
        self,
        *,
        security_id: str,
        category: str,
        title: str,
        attachment_url: str,
        published_at: datetime | None = None,
    ) -> EastmoneyDocument:
        """下载 PDF/HTML 附件，保留原始链接；解析失败直接抛出，不生成假正文。"""
        response = self.client.get(attachment_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if response.content[:4] == b"%PDF" or "pdf" in content_type:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(response.content))
            body = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        else:
            body = _html_text(response.text)
        if not body:
            raise ValueError("附件未解析出正文")
        return EastmoneyDocument(
            security_id=security_id,
            category=category,
            title=title,
            published_at=published_at,
            source="eastmoney",
            body=body,
            source_url=str(response.url),
            attachment_url=attachment_url,
        )

    def _fetch_category(self, security_id: str, key: str, category: str) -> list[EastmoneyDocument]:
        template = self.endpoint_templates.get(key, "")
        if not template:
            return []
        url = template.format(security_id=security_id)
        response = self.client.get(url)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            return _normalize_html_listing(security_id, category, url, response.text)
        rows = payload.get("data", payload) if isinstance(payload, dict) else payload
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("list", []))
        return _normalize_rows(security_id, category, url, rows if isinstance(rows, list) else [])


def _normalize_rows(
    security_id: str, category: str, base_url: str, rows: Iterable[dict[str, Any]]
) -> list[EastmoneyDocument]:
    result: list[EastmoneyDocument] = []
    seen: set[str] = set()
    for row in rows:
        title = str(row.get("title") or row.get("name") or "").strip()
        if not title:
            continue
        source_url = urljoin(base_url, str(row.get("url") or row.get("link") or ""))
        published_at = _parse_datetime(row.get("publish_time") or row.get("published_at") or row.get("date"))
        body = str(row.get("body") or row.get("content") or row.get("abstract") or "").strip()
        document = EastmoneyDocument(
            security_id=security_id,
            category=category,
            title=title,
            published_at=published_at,
            source=str(row.get("source") or row.get("institution") or "东方财富"),
            body=_html_text(body),
            source_url=source_url,
            attachment_url=row.get("pdf_url") or row.get("attachment_url"),
            author=row.get("author"),
            rating=row.get("rating") or row.get("rating_name"),
            institution=row.get("institution"),
            analyst=row.get("analyst"),
            interactions={
                key: int(row.get(key) or 0)
                for key in ("view_count", "comment_count", "like_count")
                if row.get(key) is not None
            } or None,
        )
        if document.content_hash not in seen:
            seen.add(document.content_hash)
            result.append(document)
    return result


def _normalize_html_listing(
    security_id: str, category: str, base_url: str, source: str
) -> list[EastmoneyDocument]:
    """解析东方财富栏目页面中的公开链接和内嵌日期。"""
    source = html.unescape(source)
    result: list[EastmoneyDocument] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S
    )
    for match in pattern.finditer(source):
        href, raw_title = match.groups()
        title = _html_text(raw_title)
        if len(title) < 4 or title in {"公告", "研报", "资讯", "更多", "公告列表", "个股研报", "行业列表", "首页", "行情中心"}:
            continue
        if not any(token in href.lower() for token in ("notice", "report", "news", "pdf", "info")):
            continue
        source_url = urljoin(base_url, href)
        context = source[max(0, match.start() - 180) : match.end() + 180]
        date_match = re.search(r"20\d{2}[-年/]\d{1,2}[-月/]\d{1,2}", context)
        published_at = _parse_datetime(date_match.group(0).replace("年", "-").replace("月", "-").replace("日", "")) if date_match else None
        document = EastmoneyDocument(
            security_id=security_id,
            category=category,
            title=title,
            published_at=published_at,
            source="东方财富",
            body=title,
            source_url=source_url,
            attachment_url=source_url if href.lower().endswith(".pdf") else None,
        )
        if document.content_hash not in seen:
            seen.add(document.content_hash)
            result.append(document)
    return result


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("/", "-").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:19], pattern)
            except ValueError:
                continue
    return None


def _html_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()
