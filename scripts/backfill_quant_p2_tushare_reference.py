"""使用显式 Tushare 10k 凭证补齐 P2 研究池点时市值和涨跌停缓存。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from analytics.pipelines.quant_research_universe import (
    DEFAULT_UNIVERSE_PATH,
    load_quant_research_universe,
)
from scripts.refresh_tushare_reference_cache import backfill_history
from scripts.refresh_tushare_reference_cache import run as refresh_reference_cache

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "real_data"
    / "quant"
    / "akshare-qfq-p2a30-20260901-v1"
    / "manifest.json"
)
DEFAULT_CACHE_ROOT = PROJECT_ROOT / ".runtime" / "quant-reference-cache-p2-10000"
DEFAULT_PERMISSION_REPORT = (
    PROJECT_ROOT / ".runtime" / "governance" / "tushare-permission-probe-10000.json"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE_PATH)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--tushare-token-file", type=Path, required=True)
    parser.add_argument("--tushare-token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--tushare-api-url-env", default="TUSHARE_API_URL")
    parser.add_argument(
        "--tushare-permission-profile", type=Path, default=DEFAULT_PERMISSION_REPORT
    )
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    args = parser.parse_args()
    universe = load_quant_research_universe(args.universe)
    refresh_result = refresh_reference_cache(
        current_manifest=args.current_manifest,
        cache_root=args.cache_root,
        token_file=args.tushare_token_file,
        token_env=args.tushare_token_env,
        api_url_env=args.tushare_api_url_env,
        permission_profile_path=args.tushare_permission_profile,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        companies=universe.companies,
    )
    history_result = backfill_history(
        current_manifest=args.current_manifest,
        cache_root=args.cache_root,
        token_file=args.tushare_token_file,
        token_env=args.tushare_token_env,
        api_url_env=args.tushare_api_url_env,
        permission_profile_path=args.tushare_permission_profile,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
        companies=universe.companies,
    )
    component_statuses = {str(refresh_result["status"]), str(history_result["status"])}
    overall_status = (
        "failed"
        if "failed" in component_statuses
        else ("ready" if component_statuses <= {"ready", "reused"} else "partial")
    )
    result = {
        "schema_version": "quant-p2-tushare-reference-report-v1",
        "status": overall_status,
        "latest_snapshot": refresh_result,
        "history": history_result,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
