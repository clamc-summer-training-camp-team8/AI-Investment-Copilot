"""20 组对照任务：机器耗时实测 + 人工基线待录入。

**这个模块刻意不生成人工基线时长。** 说明书目标 3 要求「同一任务耗时相对人工基线
明显下降」，人工基线必须由研究员真实计时得到。编造一个「人工 30 分钟 vs AI 2 秒」
的对照表能让报表好看，但那是假数据，且会直接推导出错误的时间节省率。

指标字典 MET-005 已经写明处理规则：**缺少人工时间则不计算**。本模块实现这条规则——
机器侧耗时真实测量，人工侧留空，时间节省率与提前量在人工数据录入前不输出数字。

任务清单覆盖研究员的真实动作：查某公司某季度的事件、判断某条假设是否被突破、
汇总某个观察期的证据。每个任务的机器侧都真实执行一遍并计时。

录入人工基线的方法：
    1. 研究员用现有流程（翻公告、查财报、手工记录）完成同一任务并计时
    2. 把分钟数填进 `real_data/dataset/manual_baseline.csv`
    3. 重跑本模块，时间节省率与提前量自动计算

用法：
    python -m analytics.evaluation.efficiency_tasks
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from datetime import datetime

from analytics.evaluation.candidate_v2 import predict as candidate_predict
from analytics.evaluation.metrics import EfficiencyMetrics
from analytics.pipelines.universe import COMPANIES
from app.core.config import PROJECT_ROOT

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
REPORT_DIR = PROJECT_ROOT / "real_data" / "reports"
BASELINE_FILE = DATASET_DIR / "manual_baseline.csv"

QUARTER_RANGES: tuple[tuple[str, str, str], ...] = (
    ("2024Q1", "2024-01-01", "2024-03-31"),
    ("2024Q2", "2024-04-01", "2024-06-30"),
    ("2024Q3", "2024-07-01", "2024-09-30"),
    ("2024Q4", "2024-10-01", "2024-12-31"),
    ("2025Q1", "2025-01-01", "2025-03-31"),
    ("2025Q2", "2025-04-01", "2025-06-30"),
    ("2025Q3", "2025-07-01", "2025-09-30"),
)


@dataclass
class TaskResult:
    """一组对照任务。

    `manual_minutes` 为 None 表示人工基线尚未录入——这不是缺陷，是当前真实状态。
    """

    task_id: str
    description: str
    machine_seconds: float
    output_count: int
    manual_minutes: float | None = None
    manual_recorded_by: str = ""

    @property
    def machine_minutes(self) -> float:
        return self.machine_seconds / 60


def _load_events() -> list[dict]:
    with (DATASET_DIR / "events.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _load_manual_baseline() -> dict[str, tuple[float, str]]:
    """读入人工基线。文件不存在或为空是正常状态。"""
    if not BASELINE_FILE.exists():
        return {}
    result: dict[str, tuple[float, str]] = {}
    with BASELINE_FILE.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("manual_minutes") or "").strip()
            if not raw:
                continue
            try:
                result[row["task_id"]] = (float(raw), row.get("recorded_by", ""))
            except ValueError:
                continue
    return result


def _task_screen_events(events: list[dict], security_id: str, start: str, end: str):
    """任务类型 A：筛出某公司某季度与核心假设相关的事件并判方向。"""
    hits = []
    for event in events:
        if event["security_id"] != security_id:
            continue
        if not (start <= event["disclosure_time"][:10] <= end):
            continue
        output = candidate_predict(event["title"])
        if output.hypothesis:
            hits.append((event["event_id"], output.hypothesis, output.direction))
    return hits


def run_tasks() -> list[TaskResult]:
    """执行 21 组任务（3 家公司 × 7 个季度）并计时。"""
    events = _load_events()
    baseline = _load_manual_baseline()
    results: list[TaskResult] = []

    for company in COMPANIES:
        for quarter, start, end in QUARTER_RANGES:
            task_id = f"TASK-{company.security_id}-{quarter}"
            started = time.perf_counter()
            hits = _task_screen_events(events, company.security_id, start, end)
            elapsed = time.perf_counter() - started

            manual = baseline.get(task_id)
            results.append(
                TaskResult(
                    task_id=task_id,
                    description=f"筛选 {company.name} {quarter} 与核心假设相关的事件并判断方向",
                    machine_seconds=elapsed,
                    output_count=len(hits),
                    manual_minutes=manual[0] if manual else None,
                    manual_recorded_by=manual[1] if manual else "",
                )
            )
    return results


def summarize(results: list[TaskResult]) -> EfficiencyMetrics:
    """只用已录入人工基线的任务计算。分母是那部分任务数，不是全部。"""
    paired = [r for r in results if r.manual_minutes is not None]
    return EfficiencyMetrics(
        task_count=len(paired),
        manual_minutes_total=sum(r.manual_minutes or 0 for r in paired),
        assisted_minutes_total=sum(r.machine_minutes for r in paired),
        lead_hours_mean=None,
    )


def ensure_baseline_template(results: list[TaskResult]) -> None:
    """生成待填写的人工基线模板。已存在则不覆盖，避免冲掉研究员填的数据。"""
    if BASELINE_FILE.exists():
        return
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    with BASELINE_FILE.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["task_id", "description", "manual_minutes", "recorded_by", "recorded_at", "note"]
        )
        for result in results:
            writer.writerow([result.task_id, result.description, "", "", "", ""])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    results = run_tasks()
    ensure_baseline_template(results)
    metrics = summarize(results)

    machine_total = sum(r.machine_seconds for r in results)
    lines = [
        "# 研究效率对照任务",
        "",
        f"生成时间: {datetime.now().astimezone().isoformat()}",
        f"任务组数: {len(results)}（说明书目标 3 要求不少于 20 组）",
        f"机器侧总耗时: {machine_total:.3f} 秒",
        f"机器侧产出: {sum(r.output_count for r in results)} 条相关事件判断",
        "",
        "## 时间节省率与提前量",
        "",
    ]

    if metrics.task_count == 0:
        lines.extend(
            [
                "**未计算。** 人工基线时长尚未录入。",
                "",
                "指标字典 MET-005 规定「缺少人工时间则不计算」，因此这里不给数字。",
                "编造人工基线能让时间节省率看起来很好，但那个数字没有意义。",
                "",
                f"录入方式：填写 `{BASELINE_FILE.relative_to(PROJECT_ROOT)}` 的 "
                "`manual_minutes` 列后重跑本模块。",
                "",
                "**说明书目标 3（研究效率）当前状态：未达成**，阻塞项是人工基线数据。",
                "",
            ]
        )
    else:
        lines.extend(f"- {line}" for line in metrics.render())
        lines.append("")

    lines.extend(
        [
            "## 逐任务机器侧耗时",
            "",
            "| 任务 | 机器耗时(秒) | 产出条数 | 人工基线(分钟) |",
            "| --- | --- | --- | --- |",
        ]
    )
    for result in results:
        manual = f"{result.manual_minutes:.1f}" if result.manual_minutes is not None else "待录入"
        lines.append(
            f"| {result.task_id} | {result.machine_seconds:.4f} | {result.output_count} | {manual} |"
        )
    lines.append("")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "efficiency_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines[:24]))
    print(f"→ {REPORT_DIR / 'efficiency_report.md'}")


if __name__ == "__main__":
    main()
