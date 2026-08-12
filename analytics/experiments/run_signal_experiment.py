"""候选信号实验：事件方向 → 20 日行业中性超额收益（DA-AC-06）。

经济假设、固化规则、偏差控制声明见
`analytics/experiments/20260811-三行业事件方向信号/README.md`，写在看结果之前。

用法：
    python -m analytics.experiments.run_signal_experiment
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import mean

from analytics.evaluation.candidate_v2 import predict as candidate_predict
from analytics.pipelines.return_labels import QuoteBook, ReturnLabel, build_label, is_hit
from analytics.pipelines.universe import BENCHMARKS, INDUSTRIES
from app.core.config import PROJECT_ROOT
from app.core.enums import ImpactDirection

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
# 研究范围、基准与词表已变化，因此新开实验目录，保留旧实验的可追溯性。
EXPERIMENT_DIR = PROJECT_ROOT / "analytics" / "experiments" / "20260811-三行业事件方向信号"
EXPERIMENT_ID = "EXP-20260811-001"


@dataclass
class SignalRecord:
    event_id: str
    security_id: str
    company: str
    title: str
    disclosure_time: str
    split: str
    hypothesis: str
    direction: str
    window_start: str
    window_end: str
    excess_return: Decimal | None
    label_status: str
    hit: bool | None
    industry: str = ""
    source_event_count: int = 1
    source_event_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateEvent:
    event_id: str
    security_id: str
    company: str
    title: str
    disclosure_time: str
    split: str
    hypothesis: str
    direction: str
    label: ReturnLabel
    industry: str = ""


@dataclass(frozen=True)
class DedupStats:
    raw_directional_events: int
    same_day_groups: int
    duplicate_events_removed: int
    conflicting_groups_removed: int
    output_signals: int


def _direction(value: str) -> str:
    return ImpactDirection.CONFLICT.value if value == "削弱" else value


def deduplicate_candidates(
    candidates: list[CandidateEvent],
) -> tuple[list[SignalRecord], DedupStats]:
    """Merge same-security/same-trading-day signals before measuring outcomes.

    Same-direction events become one observation.  A group containing support
    and conflict is neutral by mentor ruling and therefore leaves the directional
    signal experiment for human review.
    """
    grouped: dict[tuple[str, str], list[CandidateEvent]] = defaultdict(list)
    for candidate in candidates:
        trading_day = candidate.label.window_start or candidate.disclosure_time[:10]
        grouped[(candidate.security_id, trading_day)].append(candidate)

    records: list[SignalRecord] = []
    conflicting_groups = 0
    for group in grouped.values():
        directions = {_direction(item.direction) for item in group}
        if len(directions) != 1:
            conflicting_groups += 1
            continue
        first = max(group, key=lambda item: item.disclosure_time)
        direction = directions.pop()
        hypotheses = sorted({item.hypothesis for item in group if item.hypothesis})
        records.append(
            SignalRecord(
                event_id=first.event_id,
                security_id=first.security_id,
                company=first.company,
                industry=first.industry,
                title=first.title,
                disclosure_time=first.disclosure_time,
                split=(
                    "out_of_sample"
                    if any(item.split == "out_of_sample" for item in group)
                    else first.split
                ),
                hypothesis=" / ".join(hypotheses),
                direction=direction,
                window_start=first.label.window_start,
                window_end=first.label.window_end,
                excess_return=first.label.excess_return,
                label_status=first.label.status,
                hit=is_hit(direction, first.label),
                source_event_count=len(group),
                source_event_ids=tuple(item.event_id for item in group),
            )
        )

    return records, DedupStats(
        raw_directional_events=len(candidates),
        same_day_groups=len(grouped),
        duplicate_events_removed=sum(max(0, len(group) - 1) for group in grouped.values()),
        conflicting_groups_removed=conflicting_groups,
        output_signals=len(records),
    )


def collect_with_stats(book: QuoteBook) -> tuple[list[SignalRecord], DedupStats]:
    """Generate labels, then enforce the mentor's same-day deduplication ruling."""
    candidates: list[CandidateEvent] = []
    with (DATASET_DIR / "events.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            output = candidate_predict(row["title"])
            direction = _direction(output.direction)
            if direction not in {
                ImpactDirection.SUPPORT.value,
                ImpactDirection.CONFLICT.value,
            }:
                continue

            label = build_label(
                book,
                security_id=row["security_id"],
                disclosure_time=row["disclosure_time"],
            )
            candidates.append(
                CandidateEvent(
                    event_id=row["event_id"],
                    security_id=row["security_id"],
                    company=row["company"],
                    industry=row.get("industry", ""),
                    title=row["title"],
                    disclosure_time=row["disclosure_time"],
                    split=row["split"],
                    hypothesis=output.hypothesis,
                    direction=direction,
                    label=label,
                )
            )
    return deduplicate_candidates(candidates)


def collect(book: QuoteBook) -> list[SignalRecord]:
    """Backward-compatible record-only entry point."""
    records, _ = collect_with_stats(book)
    return records


@dataclass(frozen=True)
class UnconditionalBaseline:
    sample_count: int
    expected_hit_rate: float | None
    mean_excess: float | None


def unconditional_baseline(records: list[SignalRecord], book: QuoteBook) -> UnconditionalBaseline:
    """Compare signals with every same-security trading day in the same period."""
    if not records:
        return UnconditionalBaseline(0, None, None)
    start = min(record.disclosure_time[:10] for record in records)
    end = max(record.disclosure_time[:10] for record in records)
    pools = {
        security_id: book.unconditional_excess_returns(security_id, start=start, end=end)
        for security_id in {record.security_id for record in records}
    }
    expected_rates: list[float] = []
    for record in records:
        pool = pools[record.security_id]
        if not pool:
            continue
        if record.direction == ImpactDirection.SUPPORT.value:
            expected_rates.append(sum(value > 0 for value in pool) / len(pool))
        elif record.direction == ImpactDirection.CONFLICT.value:
            expected_rates.append(sum(value < 0 for value in pool) / len(pool))
    all_values = [value for pool in pools.values() for value in pool]
    return UnconditionalBaseline(
        sample_count=len(all_values),
        expected_hit_rate=mean(expected_rates) if expected_rates else None,
        mean_excess=round(mean(float(value) for value in all_values), 4) if all_values else None,
    )


@dataclass
class Summary:
    """一个子集的统计。分母全部显式给出（说明书发布门槛）。"""

    label: str
    signal_count: int
    labeled_count: int
    pending_count: int
    hit_count: int
    judgeable_count: int
    mean_excess: float | None
    positive_signals: int
    negative_signals: int
    unconditional_sample_count: int
    unconditional_hit_rate: float | None
    unconditional_mean_excess: float | None

    @property
    def hit_rate(self) -> float | None:
        if self.judgeable_count == 0:
            return None
        return self.hit_count / self.judgeable_count

    def render(self) -> list[str]:
        lines = [
            f"信号数: {self.signal_count}（支持 {self.positive_signals} / 冲突 {self.negative_signals}）",
            f"标签已生成: {self.labeled_count}，待观察: {self.pending_count}",
        ]
        if self.hit_rate is None:
            lines.append("20 日命中率: 无可判定样本（分母 0）")
        else:
            lines.append(
                f"20 日命中率: {self.hit_rate:.1%} ({self.hit_count}/{self.judgeable_count})"
            )
        if self.mean_excess is None:
            lines.append("平均 20 日超额收益: 无样本")
        else:
            lines.append(f"平均 20 日超额收益: {self.mean_excess:+.2f}%")
        if self.unconditional_hit_rate is None:
            lines.append("同期同证券无条件命中率: 无可用基准窗口")
        else:
            lift = (
                self.hit_rate - self.unconditional_hit_rate if self.hit_rate is not None else None
            )
            lift_text = "不可比较" if lift is None else f"{lift:+.1%}"
            lines.append(
                "同期同证券无条件命中率: "
                f"{self.unconditional_hit_rate:.1%} (n={self.unconditional_sample_count})；"
                f"信号相对差 {lift_text}"
            )
        if self.unconditional_mean_excess is not None:
            lines.append(f"同期同证券无条件平均超额: {self.unconditional_mean_excess:+.2f}%")
        return lines


def summarize(label: str, records: list[SignalRecord], book: QuoteBook) -> Summary:
    labeled = [r for r in records if r.label_status == "已生成"]
    judgeable = [r for r in labeled if r.hit is not None]
    excesses = [float(r.excess_return) for r in labeled if r.excess_return is not None]
    baseline = unconditional_baseline(records, book)
    return Summary(
        label=label,
        signal_count=len(records),
        labeled_count=len(labeled),
        pending_count=len(records) - len(labeled),
        hit_count=sum(1 for r in judgeable if r.hit),
        judgeable_count=len(judgeable),
        mean_excess=round(mean(excesses), 4) if excesses else None,
        positive_signals=sum(1 for r in records if r.direction == "支持"),
        negative_signals=sum(1 for r in records if r.direction == ImpactDirection.CONFLICT.value),
        unconditional_sample_count=baseline.sample_count,
        unconditional_hit_rate=baseline.expected_hit_rate,
        unconditional_mean_excess=baseline.mean_excess,
    )


def failure_cases(records: list[SignalRecord], limit: int = 5) -> dict[str, list[str]]:
    """命中、误报、待观察各取若干条（说明书 10.2 第 6 步要求同时展示失败案例）。"""
    labeled = [r for r in records if r.label_status == "已生成" and r.hit is not None]
    hits = [r for r in labeled if r.hit]
    misses = [r for r in labeled if not r.hit]
    pending = [r for r in records if r.label_status == "待观察"]

    def fmt(record: SignalRecord) -> str:
        excess = (
            f"{float(record.excess_return):+.2f}%" if record.excess_return is not None else "无标签"
        )
        return (
            f"{record.disclosure_time[:10]} {record.company} "
            f"[{record.direction}] {record.title[:32]} → 超额 {excess}"
        )

    return {
        "命中样本": [fmt(r) for r in hits[:limit]],
        "误报样本": [fmt(r) for r in misses[:limit]],
        "待观察样本": [fmt(r) for r in pending[:limit]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    book = QuoteBook()
    records, dedup = collect_with_stats(book)

    in_sample = [r for r in records if r.split == "in_sample"]
    out_sample = [r for r in records if r.split == "out_of_sample"]

    summaries = [
        summarize("样本内", in_sample, book),
        summarize("样本外", out_sample, book),
        summarize("全样本", records, book),
    ]
    summaries.extend(
        summarize(f"行业：{industry}", [r for r in records if r.industry == industry], book)
        for industry in INDUSTRIES
    )

    lines = [
        f"# 候选信号实验结果 {EXPERIMENT_ID}",
        "",
        f"生成时间: {datetime.now().astimezone().isoformat()}",
        f"行情数据版本: {book.data_version}（前复权，基准按行业取）",
        "基准: " + "、".join(f"{k}→{v.name}({v.security_id})" for k, v in BENCHMARKS.items()),
        f"行情截止日: {book.last_trading_day}",
        "窗口: 20 个交易日，T+1 起算，窗口结束后生成标签",
        (
            "同日去重: 原始方向事件 "
            f"{dedup.raw_directional_events} → {dedup.output_signals} 个独立信号；"
            f"合并重复 {dedup.duplicate_events_removed} 条，"
            f"方向冲突转人工 {dedup.conflicting_groups_removed} 组"
        ),
        "",
        "经济假设与偏差控制声明见同目录 README.md（写于结果观察之前）。",
        "",
    ]

    for summary in summaries:
        lines.append(f"## {summary.label}")
        lines.append("")
        lines.extend(f"- {line}" for line in summary.render())
        lines.append("")

    lines.append("## 失败案例与命中案例")
    lines.append("")
    for name, cases in failure_cases(records).items():
        lines.append(f"### {name}")
        if cases:
            lines.extend(f"- {case}" for case in cases)
        else:
            lines.append("- 无")
        lines.append("")

    out_summary = summaries[1]
    rate = out_summary.hit_rate
    lines.extend(
        [
            "## 结论",
            "",
            "结论等级：**探索性**。",
            "",
        ]
    )
    if rate is None:
        lines.append("样本外无可判定样本，不给出方向性结论。")
    else:
        comparison = out_summary.unconditional_hit_rate
        if comparison is None:
            verdict = (
                f"样本外 20 日命中率 {rate:.1%}，但同期同证券无条件基准不可用，"
                "不作方向预测力判断。"
            )
        else:
            distance = rate - comparison
            verdict = (
                f"样本外 20 日命中率 {rate:.1%}，同期同证券无条件期望为 "
                f"{comparison:.1%}，相差 {distance:+.1%}。"
                "样本量与时间跨度不足以排除行业行情与噪音的解释，"
                "**不构成信号有效的证据**，需更长周期样本外验证。"
            )
        lines.append(verdict)

    lines.extend(
        [
            "",
            "无论命中率高低，本实验都不支持以下表述：",
            "",
            "- 「AI 已证明能够稳定创造 Alpha」（说明书表述红线）",
            "- 任何可交易收益的推断（未考虑停牌、涨跌停、成本与换手）",
            "",
            "限制见 README.md 第 8 节。",
            "",
        ]
    )

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    (EXPERIMENT_DIR / "result.md").write_text("\n".join(lines), encoding="utf-8")

    def _range(subset: list[SignalRecord]) -> str:
        if not subset:
            return "无样本"
        days = sorted(record.disclosure_time[:10] for record in subset)
        return f"{days[0]}~{days[-1]}"

    ledger = {
        "experiment_id": EXPERIMENT_ID,
        "实验名称": "三行业事件方向信号的20日超额收益对照",
        "经济假设": "经营类事件的方向判断包含未被价格完全反映的短期基本面信息",
        "信号类型": "事件方向信号",
        "研究范围": f"{'、'.join(INDUSTRIES)}，每行业 3 家公司",
        "基准": "按行业分别取（科创50 / 中证医药 / 中证新能源汽车），前复权",
        "模型版本": "local-rule-v1 + candidate_v2",
        "数据集版本": "cninfo-announcement-v2 / tencent-qfq-v1",
        "样本内区间": _range(in_sample),
        "样本外区间": _range(out_sample),
        "样本内信号数": summaries[0].signal_count,
        "样本外信号数": out_summary.signal_count,
        "20日命中率": out_summary.hit_rate,
        "同期同证券无条件命中率": out_summary.unconditional_hit_rate,
        "相对无条件基准": (
            None
            if out_summary.hit_rate is None or out_summary.unconditional_hit_rate is None
            else out_summary.hit_rate - out_summary.unconditional_hit_rate
        ),
        "平均20日超额收益": out_summary.mean_excess,
        "同日去重统计": vars(dedup),
        "结论等级": "探索性",
        "分行业结果": {
            industry: vars(
                summarize(industry, [r for r in records if r.industry == industry], book)
            )
            for industry in INDUSTRIES
        },
        "主要限制": (
            "独立盲标显示方向一致率仍低；9家公司约2.5年样本；未考虑交易可实现性；"
            "两家港股个股为港币计价而汽车基准为人民币计价，汇率波动进入超额收益"
        ),
        "实验状态": "已完成一轮",
    }
    (EXPERIMENT_DIR / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
