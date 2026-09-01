from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.collection.investoday import InvestodayError, InvestodayNews, InvestodayNewsClient
from app.workers.news_collection import _item_mentions_security, _match_security


@pytest.mark.asyncio
async def test_新闻客户端解析供应商分页结果(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(
        200,
        json={
            "code": 0,
            "data": {
                "items": [
                    {
                        "newsId": "N-1",
                        "title": "吉利汽车发布月度销量",
                        "date": "2026-08-30T09:00:00+08:00",
                        "summary": "新能源销量增长",
                        "keyPoints": ["交付增长", "海外市场"],
                    }
                ]
            },
        },
    )

    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, *_: object, **__: object) -> httpx.Response:
            return response

    monkeypatch.setattr("app.collection.investoday.httpx.AsyncClient", FakeClient)

    news = await InvestodayNewsClient(
        api_key="secret", base_url="https://example.test"
    ).fetch_latest(page_size=10)

    assert len(news) == 1
    assert news[0].news_id == "N-1"
    assert news[0].published_at == datetime(2026, 8, 30, 1, tzinfo=UTC)
    assert "newsId=N-1" in news[0].as_text()


@pytest.mark.asyncio
async def test_新闻客户端不接受供应商错误(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, **_: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, *_: object, **__: object) -> httpx.Response:
            return httpx.Response(200, json={"code": 401, "message": "invalid key"})

    monkeypatch.setattr("app.collection.investoday.httpx.AsyncClient", FakeClient)

    with pytest.raises(InvestodayError, match="invalid key"):
        await InvestodayNewsClient(api_key="secret", base_url="https://example.test").fetch_latest(
            page_size=10
        )


def test_仅路由唯一命中的覆盖公司() -> None:
    class Security:
        def __init__(self, security_id: str, name: str, ticker: str, aliases: list[str]) -> None:
            self.security_id = security_id
            self.name = name
            self.ticker = ticker
            self.aliases = aliases

    securities = [
        Security("SEC-GL", "吉利汽车", "0175.HK", ["吉利"]),
        Security("SEC-BYD", "比亚迪", "1211.HK", ["BYD"]),
    ]
    item = InvestodayNews("N-1", "吉利汽车发布月度销量", datetime.now(tz=UTC))
    assert _match_security(item, securities) == "SEC-GL"

    ambiguous = InvestodayNews("N-2", "吉利与比亚迪供应链合作", datetime.now(tz=UTC))
    assert _match_security(ambiguous, securities) is None
    assert _item_mentions_security(item, securities[0])
    assert not _item_mentions_security(
        InvestodayNews("N-3", "海外宏观市场新闻", datetime.now(tz=UTC)), securities[0]
    )
