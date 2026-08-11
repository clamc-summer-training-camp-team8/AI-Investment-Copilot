"""候选信号实验：事件方向 → 20 日行业中性超额收益（DA-AC-06）。

经济假设、固化规则、偏差控制声明见
`analytics/experiments/20260809-事件方向信号/README.md`，写在看结果之前。

用法：
    python -m analytics.experiments.run_signal_experiment
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import mean

from analytics.evaluation.candidate_v2 import predict as candidate_predict
from analytics.pipelines.return_labels import QuoteBook, build_label, is_hit
from analytics.pipelines.universe import BENCHMARKS, INDUSTRIES
from app.core.config import PROJECT_ROOT
from app.core.enums import ImpactDirection

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
# 一实验一目录，有结果后不改配置（analytics/README.md 的实验规范）。
# 跨行业这一轮换了研究范围、基准与词表，与 20260809 那轮不可比，所以开新目录，
# 不覆盖旧结果——覆盖掉就没法回答「上一轮到底跑出了什么」。
EXPERIMENT_DIR = PROJECT_ROOT / "analytics" / "experiments" / "20260811-三行业事件方向信号"
EXPERIMENT_ID = "EXP-20260811-001"


@dataclass
class SignalRecord:
    event_id: str
    security_id: str
    company: str
    industry: str
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


DIRECTIONAL = (ImpactDirection.SUPPORT, ImpactDirection.CONFLICT)


def collect(book: QuoteBook) -> list[SignalRecord]:
    """对每条事件生成信号与收益标签。只有方向明确（支持/冲突）的才是信号。

    中性与无关不是信号：没有方向就无从判定命中，把它们算进分母会稀释命中率。
    """
    records: list[SignalRecord] = []
    with (DATASET_DIR / "events.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            output = candidate_predict(row["title"])
            if output.direction not in DIRECTIONAL:
                continue

            label = build_label(
                book,
                security_id=row["security_id"],
                disclosure_time=row["disclosure_time"],
            )
            records.append(
                SignalRecord(
                    event_id=row["event_id"],
                    security_id=row["security_id"],
                    company=row["company"],
                    industry=row.get("industry", ""),
                    title=row["title"],
                    disclosure_time=row["disclosure_time"],
                    split=row["split"],
                    hypothesis=output.hypothesis,
                    direction=output.direction,
                    window_start=label.window_start,
                    window_end=label.window_end,
                    excess_return=label.excess_return,
                    label_status=label.status,
                    hit=is_hit(output.direction, label),
                )
            )
    return records


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
        return lines


def summarize(label: str, records: list[SignalRecord]) -> Summary:
    labeled = [r for r in records if r.label_status == "已生成"]
    judgeable = [r for r in labeled if r.hit is not None]
    excesses = [float(r.excess_return) for r in labeled if r.excess_return is not None]
    return Summary(
        label=label,
        signal_count=len(records),
        labeled_count=len(labeled),
        pending_count=len(records) - len(labeled),
        hit_count=sum(1 for r in judgeable if r.hit),
        judgeable_count=len(judgeable),
        mean_excess=round(mean(excesses), 4) if excesses else None,
        positive_signals=sum(1 for r in records if r.direction == ImpactDirection.SUPPORT),
        negative_signals=sum(1 for r in records if r.direction == ImpactDirection.CONFLICT),
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
    records = collect(book)

    in_sample = [r for r in records if r.split == "in_sample"]
    out_sample = [r for r in records if r.split == "out_of_sample"]

    in_summary = summarize("样本内", in_sample)
    out_summary = summarize("样本外", out_sample)
    summaries = [in_summary, out_summary, summarize("全样本", records)]

    lines = [
        f"# 候选信号实验结果 {EXPERIMENT_ID}",
        "",
        f"生成时间: {datetime.now().astimezone().isoformat()}",
        f"行情数据版本: {book.data_version}（前复权，基准按行业取）",
        "基准: " + "、".join(f"{k}→{v.name}({v.security_id})" for k, v in BENCHMARKS.items()),
        f"行情截止日: {book.last_trading_day}",
        "窗口: 20 个交易日，T+1 起算，窗口结束后生成标签",
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

    # 分行业看样本外。混在一起报一个命中率，会把「某个行业信号有效、另一个无效」
    # 平均成「整体略好于随机」，那是最容易被误读成 alpha 的数字形态。
    lines.extend(["## 分行业（样本外）", ""])
    for industry in INDUSTRIES:
        subset = [r for r in out_sample if r.industry == industry]
        summary = summarize(industry, subset)
        lines.append(f"**{industry}**")
        lines.extend(f"- {line}" for line in summary.render())
        lines.append("")

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
        distance = abs(rate - 0.5)
        if distance < 0.05:
            verdict = (
                f"样本外 20 日命中率 {rate:.1%}，与随机（50%）的差距在 5 个百分点以内，"
                "**未观察到方向预测力**。这与实验前写下的预期一致。"
            )
        else:
            verdict = (
                f"样本外 20 日命中率 {rate:.1%}，与随机（50%）相差 {distance:.1%}。"
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

    # 区间从数据里算，不写死。原来这几项是硬编码字符串，换了样本区间也不会更新，
    # 台账会记录一个与实际实验不符的区间。
    def _range(records: list[SignalRecord]) -> str:
        if not records:
            return "无样本"
        days = sorted(r.disclosure_time[:10] for r in records)
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
        "样本内信号数": in_summary.signal_count,
        "样本外信号数": out_summary.signal_count,
        "20日命中率": out_summary.hit_rate,
        "平均20日超额收益": out_summary.mean_excess,
        "结论等级": "探索性",
        "主要限制": (
            "金标未经导师确认；9 家公司约 2.5 年样本；未考虑交易可实现性；"
            "两家港股个股为港币计价而基准为人民币计价，汇率波动进入超额收益"
        ),
        "实验状态": "已完成一轮",
    }
    (EXPERIMENT_DIR / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
