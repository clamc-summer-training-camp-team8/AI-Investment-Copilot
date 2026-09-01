"""Minimal, provider-isolated client for Investoday's licensed news feed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


class InvestodayError(RuntimeError):
    """The provider returned an unusable response; callers should not retry blindly."""


@dataclass(frozen=True)
class InvestodayNews:
    news_id: str
    title: str
    published_at: datetime
    summary: str = ""
    key_points: str = ""
    impact_analysis: str = ""
    investment_risk: str = ""
    news_type: str = ""
    sentiment: str = ""

    @property
    def item_id(self) -> str:
        return self.news_id

    def as_text(self) -> str:
        """Create a source-preserving plain-text original for the document pipeline."""

        sections = [
            ("标题", self.title),
            ("发布时间", self.published_at.isoformat()),
            ("摘要", self.summary),
            ("关键点", self.key_points),
            ("供应商影响分析（仅作线索）", self.impact_analysis),
            ("风险提示", self.investment_risk),
            ("新闻类型", self.news_type),
            ("情绪标签", self.sentiment),
            ("来源", f"今日投资新闻 API；newsId={self.news_id}"),
        ]
        return "\n\n".join(f"{label}：{value}" for label, value in sections if value)


@dataclass(frozen=True)
class InvestodayReport:
    report_id: str
    title: str
    published_at: datetime
    institution_name: str = ""
    author: str = ""
    content: str = ""
    keyword: str = ""

    @property
    def item_id(self) -> str:
        return self.report_id

    def as_text(self) -> str:
        sections = [
            ("标题", self.title),
            ("发布时间", self.published_at.isoformat()),
            ("机构", self.institution_name),
            ("作者", self.author),
            ("核心观点", self.keyword),
            ("研报内容", self.content),
            ("来源", f"今日投资研究报告 API；reportId={self.report_id}"),
        ]
        return "\n\n".join(f"{label}：{value}" for label, value in sections if value)


class InvestodayNewsClient:
    """Fetch one bounded page; the API key is deliberately never logged or serialized."""

    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float = 15) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def fetch_latest(
        self, *, page_size: int, stock_code: str | None = None
    ) -> list[InvestodayNews]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{self._base_url}/news",
                    params={
                        "pageNum": 1,
                        "pageSize": page_size,
                        **({"stockCode": stock_code} if stock_code else {}),
                    },
                    headers={"apiKey": self._api_key},
                )
        except httpx.HTTPError as exc:
            raise InvestodayError("今日投资新闻接口暂时不可用") from exc
        if response.status_code != 200:
            raise InvestodayError(f"今日投资新闻接口返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise InvestodayError("今日投资新闻接口返回了非 JSON 数据") from exc
        if not isinstance(payload, dict) or payload.get("code") not in (0, "0", None):
            raise InvestodayError(f"今日投资新闻接口返回错误：{payload.get('message', 'unknown')}")
        rows = payload.get("data") or payload.get("items") or payload.get("list") or []
        if isinstance(rows, dict):
            rows = rows.get("list") or rows.get("items") or rows.get("records") or []
        if not isinstance(rows, list):
            raise InvestodayError("今日投资新闻接口数据格式不符合预期")
        return [item for row in rows if isinstance(row, dict) if (item := _parse_news(row))]

    async def fetch_reports(self, *, stock_code: str, page_size: int) -> list[InvestodayReport]:
        today = datetime.now(tz=UTC).date()
        payload = {
            "stockCode": stock_code,
            "beginDate": (today - timedelta(days=30)).isoformat(),
            "endDate": today.isoformat(),
            "pageNum": 1,
            "pageSize": page_size,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/report/research",
                    json=payload,
                    headers={"apiKey": self._api_key},
                )
        except httpx.HTTPError as exc:
            raise InvestodayError("今日投资研报接口暂时不可用") from exc
        if response.status_code != 200:
            raise InvestodayError(f"今日投资研报接口返回 HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise InvestodayError("今日投资研报接口返回了非 JSON 数据") from exc
        if not isinstance(body, dict) or body.get("code") not in (0, "0", None):
            raise InvestodayError(f"今日投资研报接口返回错误：{body.get('message', 'unknown')}")
        rows = body.get("data") or []
        return [item for row in rows if isinstance(row, dict) if (item := _parse_report(row))]


def _parse_news(row: dict[str, Any]) -> InvestodayNews | None:
    news_id = str(row.get("newsId") or row.get("id") or "").strip()
    title = str(row.get("title") or "").strip()
    if not news_id or not title:
        return None
    return InvestodayNews(
        news_id=news_id,
        title=title,
        published_at=_parse_datetime(row.get("date") or row.get("publishTime")),
        summary=_text(row.get("summary")),
        key_points=_text(row.get("keyPoints")),
        impact_analysis=_text(row.get("impactAnalysis")),
        investment_risk=_text(row.get("investmentRisk")),
        news_type=_text(row.get("newsType")),
        sentiment=_text(row.get("sentiment")),
    )


def _parse_report(row: dict[str, Any]) -> InvestodayReport | None:
    report_id = str(row.get("reportId") or row.get("guid") or "").strip()
    title = str(row.get("title") or "").strip()
    if not report_id or not title:
        return None
    return InvestodayReport(
        report_id=report_id,
        title=title,
        published_at=_parse_datetime(row.get("date") or row.get("publishDate")),
        institution_name=_text(row.get("institutionName")),
        author=_text(row.get("author")),
        content=_text(row.get("content")),
        keyword=_text(row.get("keyword")),
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, tz=UTC)
    if isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return datetime.now(tz=UTC)


def _text(value: object) -> str:
    if isinstance(value, list):
        return "；".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()
