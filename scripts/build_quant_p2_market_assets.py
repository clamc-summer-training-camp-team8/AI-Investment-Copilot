"""按冻结 P2 研究池构建纯 A 股行情、公司行动和治理资产候选。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import cast

from analytics.pipelines.quant_price_limit_derivations import (
    load_quant_price_limit_derivations,
)
from analytics.pipelines.quant_research_universe import (
    DEFAULT_PROTOCOL_PATH,
    DEFAULT_UNIVERSE_PATH,
    load_quant_research_governance,
)
from app.ingest.market_source_secrets import (
    read_tushare_credentials_file,
    validate_tushare_api_url,
)
from scripts.build_akshare_quant_market_assets import load_tushare_permission_profile
from scripts.build_akshare_quant_market_assets import run as build_market_assets

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION = "akshare-qfq-p2a30-20260901-v1"
DEFAULT_REPORT = PROJECT_ROOT / ".runtime" / "quant-p2" / "latest-market-build.json"


def run(
    *,
    start: date,
    end: date,
    version: str = DEFAULT_VERSION,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    token_file: Path | None = None,
    token_env: str = "TUSHARE_TOKEN",
    api_url_env: str = "TUSHARE_API_URL",
    permission_report: Path | None = None,
    reference_cache_root: Path | None = None,
    price_limit_derivations_path: Path | None = None,
    report_path: Path = DEFAULT_REPORT,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> dict[str, object]:
    universe, protocol = load_quant_research_governance(universe_path, protocol_path)
    price_limit_derivation_set = (
        load_quant_price_limit_derivations(price_limit_derivations_path)
        if price_limit_derivations_path is not None
        else None
    )
    credentials = read_tushare_credentials_file(token_file) if token_file else None
    token = credentials.token if credentials else os.getenv(token_env)
    api_url = (
        credentials.api_url if credentials else validate_tushare_api_url(os.getenv(api_url_env))
    )
    endpoints: frozenset[str] = frozenset()
    permission_profile: dict[str, object] | None = None
    if token:
        if permission_report is None or not permission_report.is_file():
            raise ValueError("配置 Tushare 后必须提供对应的脱敏权限报告")
        endpoints, permission_profile = load_tushare_permission_profile(permission_report)

    destination = build_market_assets(
        start=start,
        end=end,
        version=version,
        tushare_token=token,
        tushare_api_url=api_url,
        tushare_endpoints=endpoints,
        permission_profile=permission_profile,
        reference_cache_root=reference_cache_root,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        companies=universe.companies,
        benchmarks_by_industry=universe.benchmarks,
        fetch_structured_actions=True,
        historical_controls=universe.historical_controls,
        governance_assets={
            "research_universe": universe.payload,
            "sample_protocol": protocol.payload,
            **(
                {"price_limit_derivations": price_limit_derivation_set.payload}
                if price_limit_derivation_set is not None
                else {}
            ),
        },
        price_limit_derivation_set=price_limit_derivation_set,
    )
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    capabilities = manifest["capabilities"]
    required = [
        str(item)
        for item in cast(list[object], protocol.payload["required_market_capabilities"])
    ]
    missing = sorted(key for key in required if not capabilities.get(key, False))
    evaluation_required = [
        "a_share_point_in_time_market_cap",
        "price_limit_status",
        "structured_corporate_action_events",
        "historical_universe_and_delisted_samples",
    ]
    missing_evaluation = sorted(
        key for key in evaluation_required if not capabilities.get(key, False)
    )
    report: dict[str, object] = {
        "schema_version": "quant-p2-market-build-report-v1",
        "status": "data_ready_for_accumulation" if not missing else "data_gated",
        "dataset_id": manifest["dataset_id"],
        "manifest": (destination / "manifest.json").relative_to(PROJECT_ROOT).as_posix(),
        "coverage": manifest["coverage"],
        "universe_id": universe.universe_id,
        "universe_member_count": len(universe.companies),
        "historical_control_count": len(universe.historical_controls),
        "protocol_id": protocol.protocol_id,
        "prospective_start_at": protocol.prospective_start_at,
        "required_market_capabilities": required,
        "missing_required_market_capabilities": missing,
        "evaluation_data_status": (
            "ready" if not missing_evaluation else "gated_missing_tushare_reference_data"
        ),
        "required_evaluation_market_capabilities": evaluation_required,
        "missing_evaluation_market_capabilities": missing_evaluation,
        "tushare_configured": token is not None,
        "price_limit_derivation_set_id": (
            price_limit_derivation_set.derivation_set_id
            if price_limit_derivation_set is not None
            else None
        ),
        "price_limit_derived_row_count": (
            len(price_limit_derivation_set.rows)
            if price_limit_derivation_set is not None
            else 0
        ),
        "sample_metrics": {
            "status": "requires_database_signal_audit",
            "note": "行情构建不得把既有历史关系自动计入 2026-09-01 后的前瞻样本",
        },
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if token and token in encoded:
        raise RuntimeError("安全门禁失败：P2 构建报告包含 Tushare Token")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(encoded, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2023, 12, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 8, 31))
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_PATH)
    parser.add_argument("--tushare-token-file", type=Path)
    parser.add_argument("--tushare-token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--tushare-api-url-env", default="TUSHARE_API_URL")
    parser.add_argument("--tushare-permission-report", type=Path)
    parser.add_argument("--reference-cache-root", type=Path)
    parser.add_argument("--price-limit-derivations", type=Path)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    args = parser.parse_args()
    report = run(
        start=args.start,
        end=args.end,
        version=args.version,
        universe_path=args.universe,
        protocol_path=args.protocol,
        token_file=args.tushare_token_file,
        token_env=args.tushare_token_env,
        api_url_env=args.tushare_api_url_env,
        permission_report=args.tushare_permission_report,
        reference_cache_root=args.reference_cache_root,
        price_limit_derivations_path=args.price_limit_derivations,
        report_path=args.report,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
