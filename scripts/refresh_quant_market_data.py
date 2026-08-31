"""探测新交易日并生成待人工发布的不可变量化行情候选版本。"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from analytics.pipelines.universe import BENCHMARKS, COMPANIES, Company
from app.core.config import PROJECT_ROOT, settings
from app.ingest.market_source_retry import MarketRetryEvent, call_market_source
from app.ingest.market_source_secrets import (
    read_tushare_credentials_file,
    sanitize_secret_text,
    validate_tushare_api_url,
)
from app.ingest.market_sources import AksharePrimarySource, MarketSourceError, SourceQuote
from app.services.market_data import FrozenJsonMarketData
from scripts.build_akshare_quant_market_assets import (
    DEFAULT_PERMISSION_REPORT,
    DEFAULT_REFERENCE_CACHE_ROOT,
    load_tushare_permission_profile,
)
from scripts.build_akshare_quant_market_assets import (
    run as build_market_assets,
)
from scripts.refresh_tushare_reference_cache import run as refresh_reference_cache

REPORT_ROOT = PROJECT_ROOT / ".runtime" / "quant-market-refresh"
DEFAULT_REPORT = REPORT_ROOT / "latest.json"


@dataclass(frozen=True)
class FreshnessObservation:
    security_id: str
    role: str
    market: str
    latest_date: date
    row_count: int
    rows_after_current: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FreshnessDecision:
    status: str
    target_end: date
    market_latest: dict[str, date]
    updated_markets: tuple[str, ...]
    reason: str


def assess_freshness(
    *,
    current_end: date,
    as_of: date,
    observations: list[FreshnessObservation],
) -> FreshnessDecision:
    if not observations:
        raise MarketSourceError("行情新鲜度探测没有返回任何证券")
    if any(item.latest_date > as_of for item in observations):
        raise MarketSourceError("行情源返回了晚于 --as-of 的未来交易日")

    benchmark_dates = {
        item.security_id: item.latest_date for item in observations if item.role == "benchmark"
    }
    expected_benchmarks = {item.security_id for item in BENCHMARKS.values()}
    if set(benchmark_dates) != expected_benchmarks:
        raise MarketSourceError("行业基准新鲜度探测不完整")
    if len(set(benchmark_dates.values())) != 1:
        details = ", ".join(
            f"{security_id}={day}" for security_id, day in sorted(benchmark_dates.items())
        )
        raise MarketSourceError(f"A 股行业基准最新交易日不一致: {details}")

    a_latest = max(benchmark_dates.values())
    hk_dates = [
        item.latest_date
        for item in observations
        if item.role == "security" and item.market == "港股"
    ]
    if not hk_dates:
        raise MarketSourceError("港股新鲜度探测不完整")
    market_latest = {"A股": a_latest, "港股": max(hk_dates)}
    target_end = max(market_latest.values())
    updated = tuple(market for market, latest in market_latest.items() if latest > current_end)
    if not updated:
        return FreshnessDecision(
            status="noop",
            target_end=current_end,
            market_latest=market_latest,
            updated_markets=(),
            reason=f"两个市场均没有晚于当前冻结截止日 {current_end} 的新会话",
        )
    return FreshnessDecision(
        status="update_available",
        target_end=target_end,
        market_latest=market_latest,
        updated_markets=updated,
        reason=f"发现新会话，更新市场: {','.join(updated)}",
    )


def candidate_version(
    target_end: date,
    *,
    root: Path,
    candidate_prefix: str = "akshare-qfq-tushare120",
) -> tuple[str, Path | None]:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", candidate_prefix):
        raise MarketSourceError("候选版本前缀只能使用小写字母、数字和单连字符")
    prefix = f"{candidate_prefix}-{target_end.strftime('%Y%m%d')}"
    for revision in range(1, 100):
        version = f"{prefix}-v{revision}"
        destination = root / version
        if not destination.exists():
            return version, None
        manifest_path = destination / "manifest.json"
        if manifest_path.is_file():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            coverage = payload.get("coverage")
            if (
                isinstance(coverage, dict)
                and coverage.get("end") == target_end.isoformat()
                and payload.get("status") == "frozen"
            ):
                return version, manifest_path
    raise MarketSourceError("同一交易日候选版本已超过 99 个，拒绝继续创建")


def _observe(
    primary: AksharePrimarySource,
    target: Company,
    *,
    role: str,
    start: date,
    end: date,
    current_end: date,
    max_attempts: int,
    retry_delay_seconds: float,
    retry_events: list[MarketRetryEvent],
) -> FreshnessObservation:
    operation = f"akshare.freshness.{role}.{target.security_id}"

    def fetch() -> list[SourceQuote]:
        if role == "benchmark":
            return primary.benchmark_quotes(target, start=start, end=end)
        return primary.equity_quotes(target, start=start, end=end)

    rows = call_market_source(
        operation,
        fetch,
        max_attempts=max_attempts,
        wait_seconds=retry_delay_seconds,
        events=retry_events,
    )
    return FreshnessObservation(
        security_id=target.security_id,
        role=role,
        market=target.market,
        latest_date=max(item.trading_date for item in rows),
        row_count=len(rows),
        rows_after_current=sum(item.trading_date > current_end for item in rows),
    )


def _write_report(path: Path, payload: dict[str, object], *, token: str | None) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if token and token in encoded:
        raise RuntimeError("安全门禁失败：量化刷新报告包含 Tushare Token")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")
    run_path = path.parent / "runs" / f"{payload['run_id']}.json"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(encoded, encoding="utf-8")


def run(
    *,
    current_manifest: Path,
    as_of: date,
    report_path: Path = DEFAULT_REPORT,
    token_file: Path | None = None,
    token_env: str = "TUSHARE_TOKEN",
    api_url_env: str = "TUSHARE_API_URL",
    permission_report: Path = DEFAULT_PERMISSION_REPORT,
    reference_cache_root: Path = DEFAULT_REFERENCE_CACHE_ROOT,
    candidate_prefix: str = "akshare-qfq-tushare120",
    dry_run: bool = False,
    require_tushare_crosscheck: bool = True,
    max_attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> dict[str, object]:
    started_at = datetime.now(ZoneInfo("Asia/Shanghai"))
    manifest_sha256 = sha256(current_manifest.read_bytes()).hexdigest()
    run_id = (
        f"QMR-{sha256(f'{started_at.isoformat()}:{manifest_sha256}'.encode()).hexdigest()[:20]}"
    )
    token: str | None = None
    report: dict[str, object] = {
        "schema_version": "quant-market-refresh-report-v1",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "as_of": as_of,
        "current_manifest": current_manifest.relative_to(PROJECT_ROOT).as_posix(),
        "current_manifest_sha256": manifest_sha256,
        "status": "running",
        "alert": {"severity": "none", "reason": None},
        "candidate": None,
        "registration_status": "not_registered",
    }
    retry_events: list[MarketRetryEvent] = []
    try:
        adapter = FrozenJsonMarketData(current_manifest)
        current = adapter.info()
        probe_start = current.coverage_end - timedelta(days=14)
        primary = call_market_source(
            "akshare.initialize",
            AksharePrimarySource,
            max_attempts=max_attempts,
            wait_seconds=retry_delay_seconds,
            events=retry_events,
        )
        observations = [
            _observe(
                primary,
                company,
                role="security",
                start=probe_start,
                end=as_of,
                current_end=current.coverage_end,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
                retry_events=retry_events,
            )
            for company in COMPANIES
        ]
        observations.extend(
            _observe(
                primary,
                benchmark,
                role="benchmark",
                start=probe_start,
                end=as_of,
                current_end=current.coverage_end,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
                retry_events=retry_events,
            )
            for benchmark in BENCHMARKS.values()
        )
        decision = assess_freshness(
            current_end=current.coverage_end,
            as_of=as_of,
            observations=observations,
        )
        report["freshness"] = {
            "current_coverage_end": current.coverage_end,
            "target_end": decision.target_end,
            "market_latest": decision.market_latest,
            "updated_markets": decision.updated_markets,
            "reason": decision.reason,
            "observations": [item.to_dict() for item in observations],
        }
        if decision.status == "noop":
            report["status"] = "noop"
            return report
        if dry_run:
            report["status"] = "dry_run_update_available"
            report["alert"] = {"severity": "warning", "reason": decision.reason}
            return report

        credentials = read_tushare_credentials_file(token_file) if token_file else None
        token = credentials.token if credentials else os.getenv(token_env)
        api_url = (
            credentials.api_url if credentials else validate_tushare_api_url(os.getenv(api_url_env))
        )
        if require_tushare_crosscheck and not token:
            raise MarketSourceError("发现新交易日，但未配置 Tushare Token，候选未构建")
        endpoints: frozenset[str] = frozenset()
        permission_profile: dict[str, object] | None = None
        if token:
            if not permission_report.is_file():
                raise MarketSourceError("缺少脱敏 Tushare 权限报告，候选未构建")
            endpoints, permission_profile = load_tushare_permission_profile(permission_report)

            reference_result = refresh_reference_cache(
                current_manifest=current_manifest,
                cache_root=reference_cache_root,
                token_file=token_file,
                token_env=token_env,
                api_url_env=api_url_env,
                permission_profile_path=permission_report,
                target_date=decision.target_end,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
            report["reference_cache"] = {
                "status": reference_result.get("status"),
                "daily_basic": reference_result.get("daily_basic"),
                "trade_cal": reference_result.get("trade_cal"),
                "capability_switches_changed": False,
            }

        version, existing_manifest = candidate_version(
            decision.target_end,
            root=PROJECT_ROOT / "real_data" / "quant",
            candidate_prefix=candidate_prefix,
        )
        if existing_manifest is None:
            destination = build_market_assets(
                start=current.coverage_start,
                end=decision.target_end,
                version=version,
                tushare_token=token,
                tushare_api_url=api_url,
                tushare_endpoints=endpoints,
                permission_profile=permission_profile,
                reference_cache_root=reference_cache_root,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
            candidate_manifest = destination / "manifest.json"
            status = "candidate_built"
        else:
            candidate_manifest = existing_manifest
            status = "candidate_reused"
        candidate_adapter = FrozenJsonMarketData(candidate_manifest)
        candidate_info = candidate_adapter.info()
        if candidate_info.coverage_end != decision.target_end:
            raise MarketSourceError("候选冻结截止日与新鲜度决策不一致")
        if require_tushare_crosscheck and not candidate_info.capabilities.get(
            "tushare_daily_crosscheck", False
        ):
            raise MarketSourceError("候选未通过 Tushare daily 双源门禁")
        candidate_payload = json.loads(candidate_manifest.read_text(encoding="utf-8"))
        report["status"] = status
        report["candidate"] = {
            "dataset_id": candidate_info.dataset_id,
            "data_version": candidate_info.data_version,
            "manifest": candidate_manifest.relative_to(PROJECT_ROOT).as_posix(),
            "manifest_sha256": sha256(candidate_manifest.read_bytes()).hexdigest(),
            "coverage": candidate_payload["coverage"],
            "capabilities": candidate_payload["capabilities"],
            "promotion_required": True,
        }
        return report
    except Exception as exc:
        reason = sanitize_secret_text(str(exc), secrets=(token,) if token else ())
        report["status"] = "failed"
        report["alert"] = {"severity": "critical", "reason": reason}
        return report
    finally:
        report["retry_events"] = [event.to_dict() for event in retry_events]
        report["finished_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        _write_report(report_path, report, token=token)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--current-manifest", type=Path, default=settings.quant_default_market_manifest
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tushare-token-file", type=Path)
    parser.add_argument("--tushare-token-env", default="TUSHARE_TOKEN")
    parser.add_argument("--tushare-api-url-env", default="TUSHARE_API_URL")
    parser.add_argument("--tushare-permission-report", type=Path, default=DEFAULT_PERMISSION_REPORT)
    parser.add_argument("--reference-cache-root", type=Path, default=DEFAULT_REFERENCE_CACHE_ROOT)
    parser.add_argument("--candidate-prefix", default="akshare-qfq-tushare120")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-akshare-only", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=1.0)
    args = parser.parse_args()
    result = run(
        current_manifest=args.current_manifest,
        as_of=args.as_of,
        report_path=args.report,
        token_file=args.tushare_token_file,
        token_env=args.tushare_token_env,
        api_url_env=args.tushare_api_url_env,
        permission_report=args.tushare_permission_report,
        reference_cache_root=args.reference_cache_root,
        candidate_prefix=args.candidate_prefix,
        dry_run=args.dry_run,
        require_tushare_crosscheck=not args.allow_akshare_only,
        max_attempts=args.max_attempts,
        retry_delay_seconds=args.retry_delay_seconds,
    )
    print(
        f"量化行情刷新 {result['status']} → {args.report}; " f"默认数据集未自动变更，候选需人工发布"
    )
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
