from __future__ import annotations

from pathlib import Path

import httpx

from app.ingest.notices import NoticeFetcher, NoticeRecord, parse_notice_html

HTML = """
<html><head><title>测试</title><script>ignore()</script></head>
<body><nav>导航菜单</nav><article>
<h1>云南白药业绩公告</h1>
<p>公司营业收入保持增长。</p>
<p>核心业务盈利能力有所改善。</p>
</article><footer>版权信息</footer></body></html>
"""


def _record() -> NoticeRecord:
    return NoticeRecord(
        security_id="000538.SZ",
        security_name="云南白药",
        title="云南白药业绩公告",
        notice_date="2026-08-11",
        detail_url="https://example.test/notice/1.html",
    )


def test_parse_notice_html_保留段落并设置发布时间() -> None:
    parsed = parse_notice_html(
        HTML,
        title="云南白药业绩公告",
        published_at=_record().published_at,
    )

    assert [s.content for s in parsed.segments] == [
        "云南白药业绩公告",
        "公司营业收入保持增长。",
        "核心业务盈利能力有所改善。",
    ]
    assert parsed.published_at is not None
    assert parsed.parser_version == "notice-html-v1"


def test_fetch_notice_缓存原文并返回_locator(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/notice/1.html"
        return httpx.Response(200, text=HTML, headers={"content-type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = NoticeFetcher(tmp_path, client=client).fetch(_record())

    assert result.raw_path.exists()
    assert result.source_url.endswith("/notice/1.html")
    assert result.parsed.segments[1].ordinal == 2
    assert result.parsed.published_at == _record().published_at
