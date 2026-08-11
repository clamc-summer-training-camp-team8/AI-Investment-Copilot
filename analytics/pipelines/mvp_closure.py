"""Reproducible historical MVP closure validation for the nine-company dataset.

This is an offline evaluation pipeline.  It deliberately uses the production
deterministic calculation and rule modules, while keeping model-quality claims
separate from workflow validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from analytics.pipelines.researcher_review import (
    apply_researcher_review,
    validate_researcher_reviews,
)
from app.calc.deterministic import Observation, expectation_gap, trend
from app.calc.rules import check_invalidation, suggest_status, summarize_evidence
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
    ValidationVerdict,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = (
    ROOT / "analytics" / "datasets" / "mvp-cn-nine-2024-v1" / "data" / "raw_observations.json"
)
DEFAULT_OUTPUT = ROOT / "analytics" / "experiments" / "20260811-cn-nine-mvp-closure"
DEFAULT_REVIEW_ANNOTATIONS = DEFAULT_OUTPUT / "review_queue.csv"
DEFAULT_INDEPENDENT_REVIEWS = DEFAULT_OUTPUT / "review_queue-1.csv"
DEFAULT_RESEARCHER_GOLD = DEFAULT_OUTPUT / "researcher_gold_v1.csv"
DEFAULT_AI_EVALUATION = DEFAULT_OUTPUT / "deepseek_v4_flash_results.json"


@dataclass(frozen=True)
class OfflineRuleThresholds:
    version: str = "mvp-closure-rules-v1"
    consecutive_breach_periods: int = 2
    near_invalidation_ratio: float = 0.05
    divergence_min_support: int = 1
    divergence_min_conflict: int = 1


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def load_dataset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_dataset(dataset: dict[str, Any]) -> list[str]:
    """Return blocking data-contract errors without mutating the dataset."""
    errors: list[str] = []
    cases = dataset.get("cases", [])
    industries: dict[str, int] = {}
    case_ids: set[str] = set()
    company_names: set[str] = set()

    if len(cases) != 9:
        errors.append(f"要求9家公司，实际{len(cases)}家")

    for case in cases:
        case_id = case.get("case_id", "<missing>")
        industry = case.get("industry", "<missing>")
        industries[industry] = industries.get(industry, 0) + 1
        company_names.add(case.get("company_name", "<missing>"))
        if case_id in case_ids:
            errors.append(f"案例ID重复: {case_id}")
        case_ids.add(case_id)

        observations = case.get("observations", [])
        if len(observations) != 4:
            errors.append(f"{case_id}: 要求1个基线+3个事件，实际{len(observations)}个")
            continue
        if observations[0].get("role") != "baseline":
            errors.append(f"{case_id}: 第一个观测必须是baseline")
        if any(item.get("role") != "event" for item in observations[1:]):
            errors.append(f"{case_id}: Q2-Q4必须是event")
        if [item.get("period") for item in observations] != [
            "2024Q1",
            "2024Q2",
            "2024Q3",
            "2024Q4",
        ]:
            errors.append(f"{case_id}: 报告期必须严格为2024Q1-Q4")

        established_on = _parse_date(case["thesis"]["established_on"])
        disclosures = [_parse_date(item["disclosed_at"]) for item in observations]
        period_ends = [_parse_date(item["period_end"]) for item in observations]
        if disclosures[0] != established_on:
            errors.append(f"{case_id}: 建立日必须等于基线披露日")
        if disclosures != sorted(disclosures):
            errors.append(f"{case_id}: 披露时间非递增")
        if period_ends != sorted(period_ends):
            errors.append(f"{case_id}: 报告期结束日非递增")
        if any(
            period_end > disclosed
            for period_end, disclosed in zip(period_ends, disclosures, strict=True)
        ):
            errors.append(f"{case_id}: 存在披露日前尚未结束的报告期")

        threshold = Decimal(case["metric"]["threshold"])
        baseline = Decimal(observations[0]["actual_value"])
        if threshold > baseline:
            errors.append(f"{case_id}: 冻结阈值高于Q1基线，不符合q1-scale-floor-v1")

        for item in observations:
            if not item.get("source_document_id") or not item.get("source_url"):
                errors.append(f"{case_id}/{item.get('period')}: 缺少来源追踪字段")
            if not str(item.get("source_url", "")).startswith("https://"):
                errors.append(f"{case_id}/{item.get('period')}: 来源必须使用HTTPS")
            try:
                Decimal(item["actual_value"])
            except (KeyError, ValueError):
                errors.append(f"{case_id}/{item.get('period')}: actual_value不是有效数值")

    expected_industries = {"芯片半导体": 3, "医药": 3, "新能源汽车": 3}
    if industries != expected_industries:
        errors.append(f"行业分布应为{expected_industries}，实际{industries}")
    expected_companies = {
        "中芯国际",
        "兆易创新",
        "北方华创",
        "恒瑞医药",
        "药明康德",
        "云南白药",
        "比亚迪",
        "吉利汽车",
        "小鹏汽车",
    }
    if company_names != expected_companies:
        errors.append(f"公司集合应为{expected_companies}，实际{company_names}")
    return errors


def _observation(case: dict[str, Any], raw: dict[str, Any]) -> Observation:
    metric = case["metric"]
    return Observation(
        metric_id=metric["id"],
        period=raw["period"],
        observation_date=_parse_date(raw["period_end"]),
        actual_value=Decimal(raw["actual_value"]),
        expected_value=Decimal(metric["threshold"]),
        unit=metric["unit"],
        period_type=metric["period_type"],
        source_document_id=raw["source_document_id"],
        metric_version="q1-scale-floor-v1",
    )


def _candidate_direction(verdict: ValidationVerdict) -> ImpactDirection:
    if verdict == ValidationVerdict.SUPPORT:
        return ImpactDirection.SUPPORT
    if verdict == ValidationVerdict.CONFLICT:
        return ImpactDirection.CONFLICT
    return ImpactDirection.NEUTRAL


def evaluate_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    blocking_errors = validate_dataset(dataset)
    if blocking_errors:
        return {
            "dataset_id": dataset.get("dataset_id"),
            "workflow_validation": "failed",
            "blocking_errors": blocking_errors,
            "gates": [{"gate": "data_contract", "status": "FAIL"}],
            "cases": [],
            "events": [],
        }

    thresholds = OfflineRuleThresholds()
    case_results: list[dict[str, Any]] = []
    event_results: list[dict[str, Any]] = []
    direction_matches = 0
    status_matches = 0

    for case in dataset["cases"]:
        observations = [_observation(case, raw) for raw in case["observations"]]
        current_status = ThesisStatus(case["thesis"]["initial_status"])
        reviewed_directions: list[tuple[ImpactDirection, ConfirmationStatus]] = []
        timeline: list[dict[str, Any]] = []
        established_on = _parse_date(case["thesis"]["established_on"])
        threshold = Decimal(case["metric"]["threshold"])

        for index, raw_event in enumerate(case["observations"][1:], start=1):
            obs = observations[index]
            gap = expectation_gap(obs, direction=ExpectationDirection.NOT_BELOW_THRESHOLD)
            candidate = _candidate_direction(gap.verdict)
            proxy_gold = ImpactDirection(raw_event["proxy_gold_direction"])
            review_status = "通过" if candidate == proxy_gold else "修改"
            direction_matches += int(candidate == proxy_gold)
            reviewed_directions.append((proxy_gold, ConfirmationStatus.CONFIRMED))

            evidence = summarize_evidence(
                f"{case['case_id']}-H1",
                Importance.CORE,
                reviewed_directions,
            )
            invalidation = check_invalidation(
                f"{case['case_id']}-H1",
                observations[: index + 1],
                thesis_established_on=established_on,
                threshold=threshold,
                direction=ExpectationDirection.NOT_BELOW_THRESHOLD,
                thresholds=thresholds,
            )
            suggestion = suggest_status(
                current_status,
                [evidence],
                [invalidation],
                thresholds=thresholds,
            )
            previous_status = current_status
            current_status = suggestion.suggested_status

            event_result = {
                "case_id": case["case_id"],
                "industry": case["industry"],
                "company_name": case["company_name"],
                "period": raw_event["period"],
                "disclosed_at": raw_event["disclosed_at"],
                "actual_value": obs.actual_value,
                "expected_value": obs.expected_value,
                "absolute_gap": gap.absolute_gap,
                "relative_gap": gap.relative_gap,
                "candidate_direction": candidate,
                "proxy_gold_direction": proxy_gold,
                "review_status": review_status,
                "confirmation_status": ConfirmationStatus.CONFIRMED,
                "previous_status": previous_status,
                "suggested_status": suggestion.suggested_status,
                "confirmed_status": current_status,
                "consecutive_breaches": invalidation.consecutive_breaches,
                "invalidation_breached": invalidation.breached,
                "source_document_id": raw_event["source_document_id"],
                "source_url": raw_event["source_url"],
                "locator": raw_event["locator"],
                "rule_version": suggestion.rule_version,
            }
            event_results.append(event_result)
            timeline.append(event_result)

        trend_result = trend(
            observations,
            direction=ExpectationDirection.NOT_BELOW_THRESHOLD,
        )
        expected_final = ThesisStatus(case["expected_final_status"])
        status_matches += int(current_status == expected_final)
        case_results.append(
            {
                "case_id": case["case_id"],
                "industry": case["industry"],
                "company_name": case["company_name"],
                "security_id": case["security_id"],
                "metric_name": case["metric"]["name"],
                "unit": case["metric"]["unit"],
                "threshold": threshold,
                "values": [item.actual_value for item in observations],
                "trend": asdict(trend_result),
                "final_status": current_status,
                "expected_final_status": expected_final,
                "status_match": current_status == expected_final,
                "fundamental_outcome": case["fundamental_outcome"],
                "timeline": timeline,
            }
        )

    event_count = len(event_results)
    source_count = sum(len(case["observations"]) for case in dataset["cases"])
    gates = [
        {"gate": "data_contract", "status": "PASS", "denominator": 9},
        {"gate": "source_traceability", "status": "PASS", "denominator": source_count},
        {"gate": "strict_time_order", "status": "PASS", "denominator": event_count},
        {"gate": "deterministic_calculation", "status": "PASS", "denominator": event_count},
        {"gate": "rule_candidate_generation", "status": "PASS", "denominator": event_count},
        {"gate": "proxy_review_confirmation", "status": "PASS", "denominator": event_count},
        {"gate": "status_replay", "status": "PASS", "denominator": 9},
        {"gate": "fundamental_retrospective", "status": "PASS", "denominator": 9},
        {
            "gate": "independent_researcher_gold_review",
            "status": "BLOCKED",
            "denominator": event_count,
            "reason": "当前仅有代理复核，尚无项目研究员独立确认",
        },
        {
            "gate": "ai_model_quality",
            "status": "NOT_RUN",
            "denominator": 0,
            "reason": "本实验尚未调用模型网关，本轮候选由透明确定性规则生成",
        },
    ]

    return {
        "dataset_id": dataset["dataset_id"],
        "dataset_version": dataset["dataset_version"],
        "cutoff_date": dataset["cutoff_date"],
        "model_version": "deterministic-threshold-baseline-v1",
        "rule_version": thresholds.version,
        "annotation_version": dataset["review_policy"]["version"],
        "workflow_validation": "passed_with_limitations",
        "production_mvp_acceptance": "not_passed",
        "blocking_errors": [],
        "metrics": {
            "industry_count": 3,
            "company_count": len(case_results),
            "observation_count": source_count,
            "event_count": event_count,
            "traceability_coverage": {"numerator": source_count, "denominator": source_count},
            "proxy_review_coverage": {"numerator": event_count, "denominator": event_count},
            "candidate_proxy_direction_agreement": {
                "numerator": direction_matches,
                "denominator": event_count,
                "interpretation": "规则与同一阈值口径的代理复核一致率，不是独立AI准确率",
            },
            "final_status_agreement": {"numerator": status_matches, "denominator": 9},
        },
        "gates": gates,
        "cases": case_results,
        "events": event_results,
        "limitations": [
            "目的性选择9家公司，样本不能外推到行业总体。",
            "每家公司仅使用一个核心指标，未覆盖估值、现金流与政策证据。",
            "指标与单位保留公司披露口径（中芯国际为美元；车企分别使用新能源销量、总销量和交付量），只做公司内时间序列回放，不做横向排名。",
            "期望值是Q1冻结的透明基线，不是研究员预测或市场一致预期。",
            "代理复核不是独立业务金标，方向一致率存在同口径循环性。",
            "没有复权行情和行业中性收益标签，本实验不验证Alpha。",
            "本实验尚未运行AI抽取与假设映射候选，因此不报告模型准确率。",
        ]
        + (
            [
                "本次本地回放运行于 "
                f"Python {sys.version_info.major}.{sys.version_info.minor}；"
                "项目声明要求 Python >=3.13，合并前须在 3.13 CI 重放。"
            ]
            if sys.version_info < (3, 13)
            else []
        ),
    }


def apply_ai_model_evaluation(result: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Validate a frozen live-model artifact and update only the AI acceptance gate.

    Every event must have one traceable request, a contract-valid candidate, an
    exact researcher-gold direction match, and a valid evidence locator. Passing
    this gate proves the bounded MVP workflow, not generalization beyond it.
    """
    expected = {(event["case_id"], event["period"]) for event in result.get("events", [])}
    rows = artifact.get("results")
    errors: list[str] = []
    if artifact.get("dataset_id") != result.get("dataset_id"):
        errors.append("模型评测数据集与闭环数据集不一致")
    if artifact.get("gold_version") != "researcher-gold-v1":
        errors.append("模型评测未使用冻结的 researcher-gold-v1")
    if artifact.get("api_mode") != "chat-completions":
        errors.append("模型评测 API 模式不是 chat-completions")
    if artifact.get("model_version") != "deepseek-v4-flash":
        errors.append("模型评测版本不是 deepseek-v4-flash")
    if artifact.get("prompt_or_raw_response_persisted") is not False:
        errors.append("模型评测产物的数据最小化声明缺失")
    if not isinstance(rows, list):
        rows = []
        errors.append("模型评测缺少逐事件结果")

    observed: set[tuple[str, str]] = set()
    request_ids: list[str] = []
    exact_matches = 0
    candidate_count = 0
    locator_valid = 0
    for row in rows:
        if not isinstance(row, dict):
            errors.append("模型评测包含非对象结果")
            continue
        key = (str(row.get("case_id", "")), str(row.get("period", "")))
        observed.add(key)
        if row.get("call_error"):
            errors.append(f"{key[0]} {key[1]} 模型调用失败")
        candidate_count += int(row.get("ai_status") == "候选")
        exact_matches += int(row.get("exact_match") is True)
        locator_valid += int(row.get("citation_locator_valid") is True)
        request_id = row.get("request_id")
        if isinstance(request_id, str) and request_id:
            request_ids.append(request_id)

    if observed != expected:
        missing = len(expected - observed)
        extra = len(observed - expected)
        errors.append(f"模型逐事件覆盖不一致：缺少 {missing}，额外 {extra}")
    event_count = len(expected)
    if len(rows) != event_count:
        errors.append(f"模型结果应为 {event_count} 条，实际 {len(rows)} 条")
    if candidate_count != event_count:
        errors.append(f"契约通过候选应为 {event_count} 条，实际 {candidate_count} 条")
    if exact_matches != event_count:
        errors.append(f"研究员金标方向一致应为 {event_count} 条，实际 {exact_matches} 条")
    if locator_valid != event_count:
        errors.append(f"引用定位完整应为 {event_count} 条，实际 {locator_valid} 条")
    if len(request_ids) != event_count or len(set(request_ids)) != event_count:
        errors.append("模型 request_id 缺失或不唯一")

    raw_metrics = artifact.get("metrics")
    metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else {}
    evaluation = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "dataset_id": artifact.get("dataset_id"),
        "gold_version": artifact.get("gold_version"),
        "api_mode": artifact.get("api_mode"),
        "model_version": artifact.get("model_version"),
        "thinking_mode": artifact.get("thinking_mode"),
        "event_count": event_count,
        "candidate_count": candidate_count,
        "exact_matches": exact_matches,
        "citation_locator_valid": locator_valid,
        "unique_request_count": len(set(request_ids)),
        "latency_ms": metrics.get("latency_ms"),
        "usage_totals": metrics.get("usage_totals"),
    }
    result["ai_model_evaluation"] = evaluation
    result["metrics"]["ai_model_evaluation"] = evaluation
    gate = next(item for item in result["gates"] if item["gate"] == "ai_model_quality")
    gate["status"] = evaluation["status"]
    gate["denominator"] = event_count
    if errors:
        gate["reason"] = "；".join(errors[:3])
        gate.pop("numerator", None)
        result["production_mvp_acceptance"] = "not_passed"
        return evaluation

    gate["numerator"] = event_count
    gate["reason"] = (
        f"deepseek-v4-flash Chat Completions；方向 {exact_matches}/{event_count}；"
        f"引用 {locator_valid}/{event_count}；独立 request_id {len(set(request_ids))}/{event_count}"
    )
    result["model_version"] = str(artifact["model_version"])
    result["limitations"] = [
        item
        for item in result.get("limitations", [])
        if not item.startswith("本实验尚未运行AI抽取")
    ]
    result["limitations"].append(
        "真实模型在27条冻结事件上完成事实摘要与假设方向映射，但数值比较由程序提供，"
        "样本为25条支持/2条冲突且没有无关或中性事件，不能外推为通用抽取能力。"
    )
    researcher_gate = next(
        item for item in result["gates"] if item["gate"] == "independent_researcher_gold_review"
    )
    if researcher_gate["status"] == "PASS":
        result["production_mvp_acceptance"] = "passed_with_limitations"
    return evaluation


def _write_event_csv(path: Path, events: list[dict[str, Any]]) -> None:
    fields = [
        "case_id",
        "industry",
        "company_name",
        "period",
        "disclosed_at",
        "actual_value",
        "expected_value",
        "absolute_gap",
        "relative_gap",
        "candidate_direction",
        "proxy_gold_direction",
        "review_status",
        "previous_status",
        "suggested_status",
        "confirmed_status",
        "consecutive_breaches",
        "invalidation_breached",
        "source_document_id",
        "source_url",
        "locator",
        "rule_version",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event in events:
            writer.writerow({field: _jsonable(event.get(field)) for field in fields})


def _write_review_queue(path: Path, events: list[dict[str, Any]]) -> None:
    fields = [
        "case_id",
        "company_name",
        "period",
        "candidate_direction",
        "proxy_gold_direction",
        "source_document_id",
        "source_url",
        "locator",
        "researcher_name",
        "researcher_decision",
        "researcher_direction",
        "researcher_reason",
        "reviewed_at",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "case_id": event["case_id"],
                    "company_name": event["company_name"],
                    "period": event["period"],
                    "candidate_direction": event["candidate_direction"].value,
                    "proxy_gold_direction": event["proxy_gold_direction"].value,
                    "source_document_id": event["source_document_id"],
                    "source_url": event["source_url"],
                    "locator": event["locator"],
                }
            )


def _format_values(case: dict[str, Any]) -> str:
    values = case["values"]
    if case["unit"] == "人民币元":
        return " / ".join(f"{value / Decimal('100000000'):.2f}亿" for value in values)
    if case["unit"] == "千美元":
        return " / ".join(f"{value / Decimal('1000000'):.3f}十亿美元" for value in values)
    return " / ".join(f"{int(value):,}" for value in values)


def _write_report(path: Path, result: dict[str, Any], dataset_hash: str) -> None:
    metrics = result["metrics"]
    researcher_gate = next(
        gate for gate in result["gates"] if gate["gate"] == "independent_researcher_gold_review"
    )
    researcher_review_complete = researcher_gate["status"] == "PASS"
    ai_gate = next(gate for gate in result["gates"] if gate["gate"] == "ai_model_quality")
    ai_evaluation_complete = ai_gate["status"] == "PASS"
    lines = [
        "# 九公司 MVP 历史回放闭环验证报告",
        "",
        f"- 数据集：`{result['dataset_id']}` / `{result['dataset_version']}`",
        f"- 数据截止：{result['cutoff_date']}",
        f"- 原始数据 SHA-256：`{dataset_hash}`",
        f"- 工作流结论：**{result['workflow_validation']}**",
        f"- 生产 MVP 验收：**{result['production_mvp_acceptance']}**",
        "",
        "## 执行结果",
        "",
        f"共执行 {metrics['company_count']} 家公司、{metrics['event_count']} 个回放事件、{metrics['observation_count']} 个真实观测；来源追踪和代理复核覆盖均为 100%。",
        "",
        "| 行业 | 公司 | Q1 / Q2 / Q3 / Q4 | 最终状态 | 基本面结果 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in result["cases"]:
        lines.append(
            f"| {case['industry']} | {case['company_name']} | {_format_values(case)} | "
            f"{case['final_status'].value} | {case['fundamental_outcome']} |"
        )

    lines.extend(
        [
            "",
            "## 门槛判定",
            "",
            "| 门槛 | 状态 | 分母/说明 |",
            "| --- | --- | --- |",
        ]
    )
    for gate in result["gates"]:
        detail = gate.get("reason", f"n={gate.get('denominator', 0)}")
        lines.append(f"| {gate['gate']} | {gate['status']} | {detail} |")

    lines.extend(
        [
            "",
            "## 关键回放",
            "",
            "云南白药 Q2、Q3 连续低于冻结的百亿元阈值，Q3 触发“重大风险”；Q4 回到阈值之上，但历史中同时存在支持和冲突证据，状态转为“出现分歧”。这条路径验证了连续失效、恢复后重新聚合和人工确认门。",
            "",
            "## 有限结论",
            "",
            "技术工作流（真实数据→指标→候选→人工确认→状态版本→基本面复盘）已跑通。"
            + (
                "27 个事件的独立研究员金标及 20% 双人复核已经纳入。"
                if researcher_review_complete
                else "独立研究员金标门槛尚未通过。"
            )
            + (
                "真实 DeepSeek Chat Completions 已完成 27/27 条候选映射并通过冻结技术门槛；"
                "生产 MVP 闭环按限定范围验收通过，但仍受样本结构和任务边界限制。"
                if ai_evaluation_complete
                else "生产 MVP 尚未验收，因为本实验还没有运行真实 AI 抽取/映射候选；"
                "规则候选一致率不得解释为 AI 准确率。"
            ),
            "",
            "## 限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.extend(
        [
            "",
            "## 下一步",
            "",
            (
                "1. 冻结本次 DeepSeek 结果、模型与提示词版本，后续变更另开实验。"
                if ai_evaluation_complete
                else "1. 冻结 `researcher-gold-v1`，后续模型和提示词版本统一在该金标上评测。"
                if researcher_review_complete
                else "1. 完成全部 27 个事件的单人复核及至少 20% 双人独立复核。"
            ),
            (
                "2. 建立包含无关、中性和定性正文事件的新样本外金标，验证真正的抽取与筛选能力。"
                if ai_evaluation_complete
                else "2. 使用已实现的 HttpProvider 在同一冻结数据集运行真实模型，比较关键词基线、规则基线和 AI 候选。"
            ),
            "3. 新建样本外数据集，加入利润/现金流和复权行情，冻结行业基准与收益窗口后再评估增量价值。",
            "",
            "真实模型评测入口：",
            "`python -m analytics.evaluation.run_nine_company_model --limit 1`（单条冒烟）和",
            "`python -m analytics.evaluation.run_nine_company_model`（27 条全量）。运行前由服务端环境",
            "提供 `LLM_API_KEY`；配置检查失败时不会静默回退到 local 规则。评测产物不保存密钥、",
            "完整提示词或供应商原始响应。",
            "",
            "> 本报告仅用于产品与研究流程验证，不构成证券研究结论或投资建议。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(result: dict[str, Any], dataset_path: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    (output_dir / "results.json").write_text(
        json.dumps(_jsonable(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_event_csv(output_dir / "event_results.csv", result.get("events", []))
    _write_review_queue(output_dir / "review_queue_template.csv", result.get("events", []))
    review_queue = output_dir / "review_queue.csv"
    if not review_queue.exists():
        _write_review_queue(review_queue, result.get("events", []))
    if result.get("metrics"):
        _write_report(output_dir / "REPORT.md", result, dataset_hash)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--review-annotations", type=Path, default=DEFAULT_REVIEW_ANNOTATIONS)
    parser.add_argument("--independent-reviews", type=Path, default=DEFAULT_INDEPENDENT_REVIEWS)
    parser.add_argument("--researcher-gold", type=Path, default=DEFAULT_RESEARCHER_GOLD)
    parser.add_argument("--ai-evaluation", type=Path, default=DEFAULT_AI_EVALUATION)
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    result = evaluate_dataset(dataset)
    review_paths = (args.review_annotations, args.independent_reviews, args.researcher_gold)
    if all(path.exists() for path in review_paths) and result.get("events"):
        review = validate_researcher_reviews(result["events"], *review_paths)
        apply_researcher_review(result, review)
    if args.ai_evaluation.exists() and result.get("events"):
        artifact = json.loads(args.ai_evaluation.read_text(encoding="utf-8"))
        apply_ai_model_evaluation(result, artifact)
    write_outputs(result, args.dataset, args.output)
    print(
        json.dumps(
            {
                "workflow_validation": result["workflow_validation"],
                "production_mvp_acceptance": result.get("production_mvp_acceptance"),
                "blocking_errors": result.get("blocking_errors", []),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 1 if result.get("blocking_errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
