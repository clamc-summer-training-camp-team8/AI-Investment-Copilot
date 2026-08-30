"""在冻结的九公司 27 事件金标上运行真实 Chat Completions 模型。

本入口只评估“事件事实摘要 + 相对既有假设的方向映射”。数值比较仍由程序完成，
不会让模型重算实际值与阈值。输出不保存 API Key、完整提示词或供应商原始响应。

用法：
    python -m analytics.evaluation.run_nine_company_model --limit 1
    python -m analytics.evaluation.run_nine_company_model
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.ai.contracts.validator import ValidationOutcome
from app.ai.errors import ModelUnavailable
from app.ai.gateway import Gateway
from app.core.config import PROJECT_ROOT, Settings
from app.core.enums import AiStatus

DATASET_PATH = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "mvp-cn-nine-2024-v1"
    / "data"
    / "raw_observations.json"
)
EXPERIMENT_DIR = PROJECT_ROOT / "analytics" / "experiments" / "20260811-cn-nine-mvp-closure"
GOLD_PATH = EXPERIMENT_DIR / "researcher_gold_v1.csv"
DEFAULT_JSON_PATH = EXPERIMENT_DIR / "deepseek_v4_flash_results.json"
DEFAULT_REPORT_PATH = EXPERIMENT_DIR / "DEEPSEEK_V4_FLASH_REPORT.md"


class EventGateway(Protocol):
    def event_impact(
        self,
        *,
        document_id: str,
        security_id: str,
        segment_locator: str,
        segment_text: str,
        disclosure_time: str,
        candidates: list[dict[str, Any]],
        evidence_contexts: list[dict[str, Any]],
        event_type: str = "其他",
        occurred_on: str | None = None,
    ) -> ValidationOutcome: ...


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    industry: str
    company_name: str
    security_id: str
    thesis_title: str
    thesis_statement: str
    metric_name: str
    metric_unit: str
    threshold: str
    period: str
    period_end: str
    disclosed_at: str
    actual_value: str
    source_document_id: str
    evidence: str
    gold_direction: str

    @property
    def segment_locator(self) -> str:
        return f"{self.source_document_id}#paragraph-1"

    @property
    def disclosure_time(self) -> str:
        # 原始数据只有披露日期。按当日最后一刻归一化，避免暗示盘中可得性。
        return f"{self.disclosed_at}T23:59:59+08:00"

    @property
    def deterministic_comparison(self) -> str:
        actual = Decimal(self.actual_value)
        threshold = Decimal(self.threshold)
        return "实际值不低于冻结阈值" if actual >= threshold else "实际值低于冻结阈值"


@dataclass
class CaseResult:
    case_id: str
    industry: str
    company_name: str
    security_id: str
    period: str
    source_document_id: str
    gold_direction: str
    ai_status: str
    predicted_direction: str | None
    exact_match: bool | None
    relevance: str | None
    confidence: float | None
    citation_locator_valid: bool
    latency_ms: int
    model_version: str | None = None
    prompt_version: str | None = None
    request_id: str | None = None
    usage: dict[str, Any] | None = None
    validation_errors: list[str] | None = None
    call_error: str | None = None


def load_cases(
    dataset_path: Path = DATASET_PATH,
    gold_path: Path = GOLD_PATH,
) -> list[EvaluationCase]:
    with gold_path.open(encoding="utf-8-sig", newline="") as stream:
        gold_rows = list(csv.DictReader(stream))
    gold = {
        (row["case_id"], row["period"]): row["researcher_direction"]
        for row in gold_rows
        if row["researcher_decision"] in {"通过", "修改"}
    }

    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases: list[EvaluationCase] = []
    for company_case in payload["cases"]:
        for observation in company_case["observations"]:
            if observation["role"] != "event":
                continue
            key = (company_case["case_id"], observation["period"])
            if key not in gold:
                raise ValueError(f"缺少研究员金标: {key[0]} / {key[1]}")
            cases.append(
                EvaluationCase(
                    case_id=company_case["case_id"],
                    industry=company_case["industry"],
                    company_name=company_case["company_name"],
                    security_id=company_case["security_id"],
                    thesis_title=company_case["thesis"]["title"],
                    thesis_statement=company_case["thesis"]["statement"],
                    metric_name=company_case["metric"]["name"],
                    metric_unit=company_case["metric"]["unit"],
                    threshold=company_case["metric"]["threshold"],
                    period=observation["period"],
                    period_end=observation["period_end"],
                    disclosed_at=observation["disclosed_at"],
                    actual_value=observation["actual_value"],
                    source_document_id=observation["source_document_id"],
                    evidence=observation["evidence"],
                    gold_direction=gold[key],
                )
            )
    if len(cases) != 27:
        raise ValueError(f"冻结数据集应有 27 个事件，实际为 {len(cases)}")
    return cases


def _number(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _case_result(case: EvaluationCase, outcome: ValidationOutcome, latency_ms: int) -> CaseResult:
    payload = outcome.payload
    impacts = payload.get("impacts")
    impact = impacts[0] if isinstance(impacts, list) and impacts else {}
    impact_data = impact if isinstance(impact, dict) else {}
    signal = impact_data.get("signal")
    event = payload.get("event")
    metadata = payload.get("model_metadata")
    signal_data = signal if isinstance(signal, dict) else {}
    event_data = event if isinstance(event, dict) else {}
    metadata_data = metadata if isinstance(metadata, dict) else {}
    direction = signal_data.get("impact_direction")
    predicted = direction if isinstance(direction, str) else None
    request_id = metadata_data.get("request_id")
    usage = metadata_data.get("usage")
    return CaseResult(
        case_id=case.case_id,
        industry=case.industry,
        company_name=case.company_name,
        security_id=case.security_id,
        period=case.period,
        source_document_id=case.source_document_id,
        gold_direction=case.gold_direction,
        ai_status=outcome.ai_status.value,
        predicted_direction=predicted,
        exact_match=predicted == case.gold_direction if predicted is not None else None,
        relevance=(
            impact_data.get("relevance") if isinstance(impact_data.get("relevance"), str) else None
        ),
        confidence=_number(signal_data.get("confidence")),
        citation_locator_valid=event_data.get("evidence_locator") == case.segment_locator,
        latency_ms=latency_ms,
        model_version=(
            payload.get("model_version") if isinstance(payload.get("model_version"), str) else None
        ),
        prompt_version=(
            payload.get("prompt_version")
            if isinstance(payload.get("prompt_version"), str)
            else None
        ),
        request_id=request_id if isinstance(request_id, str) else None,
        usage=usage if isinstance(usage, dict) else None,
        validation_errors=outcome.errors or None,
    )


def evaluate_cases(
    gateway: EventGateway,
    cases: list[EvaluationCase],
    *,
    limit: int | None = None,
) -> list[CaseResult]:
    selected = cases if limit is None else cases[:limit]
    results: list[CaseResult] = []
    for index, case in enumerate(selected, start=1):
        started = time.perf_counter()
        try:
            outcome = gateway.event_impact(
                document_id=case.source_document_id,
                security_id=case.security_id,
                segment_locator=case.segment_locator,
                segment_text=case.evidence,
                disclosure_time=case.disclosure_time,
                candidates=[
                    {
                        "thesis_id": case.case_id,
                        "hypothesis_id": f"{case.case_id}-H1",
                        "thesis_core_view": (f"{case.thesis_title}：{case.thesis_statement}"),
                        "statement": case.thesis_statement,
                        "importance": "核心",
                        "expected_direction": "不低于阈值",
                        "metric_rules": [
                            {
                                "metric_name": case.metric_name,
                                "metric_unit": case.metric_unit,
                                "threshold": case.threshold,
                                "observed_value": case.actual_value,
                                "deterministic_comparison": case.deterministic_comparison,
                                "calculation_owner": "program-not-model",
                            }
                        ],
                    }
                ],
                evidence_contexts=[
                    {
                        "thesis_id": case.case_id,
                        "hypothesis_id": f"{case.case_id}-H1",
                        "evidence": [
                            {
                                "context_type": "current_event_evidence",
                                "document_id": case.source_document_id,
                                "locator": case.segment_locator,
                                "content": case.evidence,
                                "published_at": case.disclosure_time,
                                "source": "evaluation-dataset",
                            }
                        ],
                    }
                ],
                event_type="业绩",
                occurred_on=case.period_end,
            )
        except ModelUnavailable as exc:
            latency = round((time.perf_counter() - started) * 1000)
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    industry=case.industry,
                    company_name=case.company_name,
                    security_id=case.security_id,
                    period=case.period,
                    source_document_id=case.source_document_id,
                    gold_direction=case.gold_direction,
                    ai_status="调用失败",
                    predicted_direction=None,
                    exact_match=None,
                    relevance=None,
                    confidence=None,
                    citation_locator_valid=False,
                    latency_ms=latency,
                    call_error=str(exc),
                )
            )
            print(f"[{index}/{len(selected)}] {case.company_name} {case.period}: 调用失败")
            if not exc.retryable:
                break
            continue

        latency = round((time.perf_counter() - started) * 1000)
        result = _case_result(case, outcome, latency)
        results.append(result)
        print(
            f"[{index}/{len(selected)}] {case.company_name} {case.period}: "
            f"{result.ai_status} / {result.predicted_direction or '无方向'}"
        )
    return results


def summarize(results: list[CaseResult], expected_count: int) -> dict[str, Any]:
    completed = [result for result in results if result.call_error is None]
    directional = [result for result in completed if result.exact_match is not None]
    matches = sum(result.exact_match is True for result in directional)
    by_gold: dict[str, dict[str, int | float | None]] = {}
    for direction, count in Counter(result.gold_direction for result in directional).items():
        subset = [result for result in directional if result.gold_direction == direction]
        matched = sum(result.exact_match is True for result in subset)
        by_gold[direction] = {
            "count": count,
            "matches": matched,
            "accuracy": matched / count if count else None,
        }

    latencies = sorted(result.latency_ms for result in completed)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1) if latencies else 0
    usage_totals: defaultdict[str, int] = defaultdict(int)
    for result in completed:
        for key, value in (result.usage or {}).items():
            if isinstance(value, int):
                usage_totals[key] += value

    return {
        "expected_count": expected_count,
        "attempted_count": len(results),
        "completed_count": len(completed),
        "candidate_count": sum(
            result.ai_status == AiStatus.CANDIDATE.value for result in completed
        ),
        "low_confidence_count": sum(
            result.ai_status == AiStatus.LOW_CONFIDENCE.value for result in completed
        ),
        "parse_failed_count": sum(
            result.ai_status == AiStatus.PARSE_FAILED.value for result in completed
        ),
        "call_failed_count": sum(result.call_error is not None for result in results),
        "directional_count": len(directional),
        "exact_matches": matches,
        "direction_accuracy": matches / len(directional) if directional else None,
        "by_gold_direction": by_gold,
        "citation_locator_integrity": (
            sum(result.citation_locator_valid for result in completed) / len(completed)
            if completed
            else None
        ),
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "p95": latencies[p95_index] if latencies else None,
        },
        "usage_totals": dict(usage_totals),
    }


def build_artifact(
    settings: Settings,
    cases: list[EvaluationCase],
    results: list[CaseResult],
) -> dict[str, Any]:
    return {
        "experiment_id": "20260811-cn-nine-mvp-closure-deepseek-v4-flash",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset_id": "mvp-cn-nine-2024-v1",
        "gold_version": "researcher-gold-v1",
        "provider": settings.llm_provider,
        "endpoint_host": httpx.URL(settings.llm_endpoint or "").host,
        "api_mode": "chat-completions",
        "model_version": settings.llm_model_version,
        "thinking_mode": settings.llm_thinking_mode,
        "prompt_or_raw_response_persisted": False,
        "disclosure_time_policy": "date-only disclosures normalized to 23:59:59+08:00",
        "evaluation_scope": "event fact summarization and hypothesis-direction mapping",
        "calculation_policy": "observed-value/threshold comparison computed by program",
        "metrics": summarize(results, len(cases)),
        "results": [asdict(result) for result in results],
    }


def _percent(value: object) -> str:
    return f"{value:.1%}" if isinstance(value, float) else "N/A"


def render_report(artifact: dict[str, Any]) -> str:
    metrics = artifact["metrics"]
    by_gold = metrics["by_gold_direction"]
    lines = [
        "# DeepSeek V4 Flash 九公司事件映射评测",
        "",
        f"- 生成时间：{artifact['generated_at']}",
        f"- API：Chat Completions / `{artifact['model_version']}`",
        f"- 金标：`{artifact['gold_version']}`",
        f"- 完成调用：{metrics['completed_count']} / {metrics['expected_count']}",
        f"- 方向一致率：{_percent(metrics['direction_accuracy'])}",
        f"- Schema 解析失败：{metrics['parse_failed_count']}",
        f"- 低置信输出：{metrics['low_confidence_count']}",
        f"- 引用定位完整率：{_percent(metrics['citation_locator_integrity'])}",
        f"- 延迟：平均 {metrics['latency_ms']['mean']} ms，P95 {metrics['latency_ms']['p95']} ms",
        "",
        "## 分方向结果",
        "",
        "| 金标方向 | 样本数 | 一致数 | 一致率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for direction, row in by_gold.items():
        lines.append(
            f"| {direction} | {row['count']} | {row['matches']} | {_percent(row['accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## 结论边界",
            "",
            "本实验只验证公开披露事实的摘要和相对既有假设的方向映射。实际值与冻结阈值的",
            "比较由程序预先完成，模型不负责关键数值计算。27 条样本来自目的性选择的 9 家公司，",
            "且类别不平衡，因此不能据此证明行业泛化能力、Alpha 或生产可用性。所有模型输出仍需人工复核。",
            "",
            "评测产物不保存 API Key、完整提示词或供应商原始响应。",
            "",
        ]
    )
    return "\n".join(lines)


def validate_deepseek_chat_config(settings: Settings) -> None:
    if settings.llm_provider != "http":
        raise ModelUnavailable("真实模型评测要求 LLM_PROVIDER=http", retryable=False)
    endpoint = httpx.URL(settings.llm_endpoint or "")
    if endpoint.host != "api.deepseek.com" or not endpoint.path.endswith("/chat/completions"):
        raise ModelUnavailable(
            "本评测要求 DeepSeek Chat Completions 端点 https://api.deepseek.com/chat/completions",
            retryable=False,
        )
    if settings.llm_model_version != "deepseek-v4-flash":
        raise ModelUnavailable("本评测要求 LLM_MODEL_VERSION=deepseek-v4-flash", retryable=False)
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        raise ModelUnavailable("本评测要求由服务端环境提供 LLM_API_KEY", retryable=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="仅运行前 N 条；冒烟测试使用 1")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_PATH)
    args = parser.parse_args()

    cases = load_cases()
    if args.limit is not None and not 1 <= args.limit <= len(cases):
        parser.error(f"--limit 必须在 1 到 {len(cases)} 之间")

    settings = Settings()
    try:
        validate_deepseek_chat_config(settings)
        gateway = Gateway.build(settings)
    except ModelUnavailable as exc:
        parser.exit(2, f"配置错误：{exc}\n")
    results = evaluate_cases(gateway, cases, limit=args.limit)
    artifact = build_artifact(settings, cases, results)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.report_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    args.report_output.write_text(render_report(artifact), encoding="utf-8")
    print(f"JSON 结果：{args.json_output}")
    print(f"Markdown 报告：{args.report_output}")


if __name__ == "__main__":
    main()
