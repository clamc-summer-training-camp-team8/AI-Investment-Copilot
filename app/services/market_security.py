"""通用证券市场主数据查询。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_SUGGEST_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_PROFILE_URL = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"


@dataclass(frozen=True)
class MarketSecurity:
    security_id: str
    name: str
    ticker: str | None
    industry: str | None


def lookup(query: str, *, client: httpx.Client | None = None) -> list[MarketSecurity]:
    """按代码或名称查询市场证券，并补充所属行业。

    证券搜索与公司画像均使用通用市场接口，不按公司编写适配器。外部接口失败时
    直接返回空列表，由 API 明确告诉前端未匹配，不用本地猜测结果。
    """
    keyword = query.strip()
    if not keyword:
        return []
    owns_client = client is None
    http = client or httpx.Client(timeout=4.0, follow_redirects=True)
    try:
        response = http.get(
            _SUGGEST_URL,
            params={"input": keyword, "type": "14", "token": _TOKEN, "count": "8"},
        )
        response.raise_for_status()
        payload = response.json()
        rows = ((payload.get("QuotationCodeTable") or {}).get("Data") or [])
        results: list[MarketSecurity] = []
        for row in rows:
            code = str(row.get("Code") or row.get("UnifiedCode") or "").strip().upper()
            name = str(row.get("Name") or "").strip()
            quote_id = str(row.get("QuoteID") or "").strip()
            if not code or not name:
                continue
            ticker = _ticker(code, quote_id)
            industry = _lookup_industry(http, ticker)
            results.append(MarketSecurity(code, name, ticker, industry))
        return results
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    finally:
        if owns_client:
            http.close()


def _lookup_industry(client: httpx.Client, ticker: str) -> str | None:
    if "." not in ticker:
        return None
    code, market = ticker.split(".", 1)
    try:
        response = client.get(
            _PROFILE_URL,
            params={"code": f"{market}{code}"},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        rows = (response.json() or {}).get("jbzl") or []
        value = rows[0].get("INDUSTRYCSRC1") if rows else None
        industry = str(value or "").strip()
        return industry if industry and industry != "-" else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def _ticker(code: str, quote_id: str) -> str:
    market = quote_id.split(".", 1)[0] if "." in quote_id else ""
    suffix = {"0": "SZ", "1": "SH", "116": "HK"}.get(market)
    return f"{code}.{suffix}" if suffix else code
