"""独立采集结果与仓库数据的交叉核对（医药三家）。

仓库的 financials.json 来自东财 F10 接口；这里的对照数字来自各期定期报告原文，
是一条独立的采集路径。两条路径核对同一批数字：对得上说明采集管道没有引入偏差，
对不上说明其中一条有问题——不管是哪条，都必须查清楚再用。

A 股年报「分季度主要财务数据」表本身即单季口径，因此这些是披露值不是推算值。

用法：python -m scripts.crosscheck_pharma
"""

from __future__ import annotations

import json
from decimal import Decimal

from app.core.config import PROJECT_ROOT

DISCLOSED: dict[str, dict[str, str]] = {
    "600276": {
        "2024Q1": "5997533912.14",
        "2024Q2": "7603200202.63",
        "2024Q3": "6588569730.33",
        "2024Q4": "7795301496.96",
        "2025Q1": "7205611122.72",
        "2025Q2": "8555582506.18",
        "2025Q3": "7426888299.87",
        "2025Q4": "8441334265.06",
        "2026Q1": "8140565320.77",
    },
    "603259": {
        "2024Q1": "7981934236.96",
        "2024Q2": "9258984026.06",
        "2024Q3": "10461083991.74",
        "2024Q4": "11539429105.12",
        "2025Q1": "9654595304.28",
        "2025Q2": "11144686578.18",
        "2025Q3": "12057434626.40",
        "2025Q4": "12599449265.32",
        "2026Q1": "12435776568.29",
    },
    "000538": {
        "2024Q1": "10774290921.49",
        "2024Q2": "9680995366.03",
        "2024Q3": "9459868782.32",
        "2024Q4": "10118145744.88",
        "2025Q1": "10841237721.29",
        "2025Q2": "10415865174.73",
        "2025Q3": "9397111312.99",
        "2025Q4": "10532784881.30",
        "2026Q1": "11602596895.18",
    },
}

NAMES = {"600276": "恒瑞医药", "603259": "药明康德", "000538": "云南白药"}

# 容差 0.5%。两个来源对同一季度的取整位数可能不同，但真实偏差应远小于此。
TOLERANCE = Decimal("0.005")


def main() -> int:
    path = PROJECT_ROOT / "real_data" / "raw" / "financials.json"
    metrics = json.loads(path.read_text(encoding="utf-8"))["metrics"]

    consistent = mismatched = missing = 0
    problems: list[str] = []

    for security_id, periods in DISCLOSED.items():
        rows = {r["period"]: r for r in metrics.get(security_id, [])}
        print(f"\n{NAMES[security_id]}（{security_id}）")
        for period, disclosed in sorted(periods.items()):
            row = rows.get(period)
            if row is None:
                missing += 1
                problems.append(f"{NAMES[security_id]} {period} 仓库缺失")
                print(f"  {period}  仓库缺失")
                continue

            expected = Decimal(disclosed)
            actual = Decimal(row["revenue"])
            deviation = abs(actual - expected) / expected

            if deviation < TOLERANCE:
                consistent += 1
                print(f"  {period}  一致    {actual / 10**8:>7.2f} 亿")
            else:
                mismatched += 1
                problems.append(
                    f"{NAMES[security_id]} {period}: 报告 {expected / 10**8:.2f} 亿 "
                    f"vs 仓库 {actual / 10**8:.2f} 亿（偏差 {deviation * 100:.2f}%）"
                )
                print(
                    f"  {period}  不一致  报告 {expected / 10**8:.2f} 亿 "
                    f"仓库 {actual / 10**8:.2f} 亿  偏差 {deviation * 100:.2f}%"
                )

    print("\n" + "=" * 56)
    print(f"一致 {consistent} | 不一致 {mismatched} | 缺失 {missing}")
    if problems:
        print("\n需核查：")
        for item in problems:
            print(f"  - {item}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
