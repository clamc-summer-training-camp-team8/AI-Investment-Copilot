"""安全探测本地 Tushare 账号对量化产品所需接口的实际权限。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics.pipelines.universe import COMPANY_BY_ID
from app.ingest.market_source_secrets import (
    read_tushare_credentials_file,
    validate_tushare_api_url,
)
from app.ingest.market_sources import MarketSourceError, TushareSupplementSource

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / ".runtime" / "governance" / "tushare-permission-probe.json"


def run(
    *,
    token_file: Path | None,
    token_env: str,
    api_url_env: str = "TUSHARE_API_URL",
    output: Path,
    security_id: str,
    trading_date: date,
    declared_points: int,
) -> Path:
    credentials = read_tushare_credentials_file(token_file) if token_file else None
    token = credentials.token if credentials else os.getenv(token_env)
    api_url = (
        credentials.api_url if credentials else validate_tushare_api_url(os.getenv(api_url_env))
    )
    if not token:
        raise MarketSourceError("没有配置 Tushare Token")
    source = TushareSupplementSource(token, api_url=api_url)
    target = COMPANY_BY_ID[security_id]
    probes = source.probe_permissions(target, trading_date=trading_date)
    payload = {
        "schema_version": "tushare-permission-probe-v1",
        "probed_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "declared_account_points": declared_points,
        "credential_source": "local_secret_file",
        "credential_persisted": False,
        "sdk_version": source.library_version,
        "api_origin": source.api_origin,
        "sample": {"security_id": security_id, "trading_date": trading_date},
        "endpoints": [
            {
                "endpoint": item.endpoint,
                "status": item.status,
                "row_count": item.row_count,
                "reason": item.reason,
            }
            for item in probes
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
    if token in encoded:
        raise RuntimeError("安全门禁失败：权限报告包含 Token")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    summary = ", ".join(f"{item.endpoint}={item.status}" for item in probes)
    print(f"Tushare 权限探测完成（Token 未持久化）：{summary} → {output}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--api-url-env", default="TUSHARE_API_URL")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--security-id", default="600276")
    parser.add_argument("--trading-date", type=date.fromisoformat, default=date(2026, 8, 28))
    parser.add_argument("--declared-points", type=int, default=120)
    args = parser.parse_args()
    run(
        token_file=args.token_file,
        token_env=args.token_env,
        api_url_env=args.api_url_env,
        output=args.output,
        security_id=args.security_id,
        trading_date=args.trading_date,
        declared_points=args.declared_points,
    )


if __name__ == "__main__":
    main()
