"""抽取独立盲标表，交业务导师标注。

**这份表的产出物不是金标，标注回来才是。** 现有金标由程序化预标注加规则裁决产生，
与被评测对象 `candidate_v2` 的词表同源；同源意味着"规则复现规则"，测出的准确率
不能读作模型能力（GAP-004 / DA-AC-05 的阻塞点）。

同源还让一致性指标失去了诊断能力：`direction_kappa = 1.0` 来自两名标注者在 2540 条
上都判"无关"、289 条都判"中性"，双方没有可分歧的空间。只有引入独立于抽取规则的
第三方标注，kappa 才重新衡量"标注规则是否清晰"而不是"两套规则有多相关"。

三条设计约束：

1. **配额按披露类型定，不按预期答案定。** 按答案配额会把答案编进抽样，
   标注回来只能验证抽样设计本身。
2. **噪音样本必须保留。** 只抽业务相关样本会让评测集偏易，测不出误报率——
   `candidate_v2` 当前无关提醒率 42.8%，这个数字只能靠含噪音的样本测出来。
3. **输出不含任何已有标注结果。** `annotator_*`、`ruling_rule`、`category` 一律不写入，
   避免锚定导师判断。类型只用于抽样配额，不进表。

用法：
    python -m analytics.pipelines.sample_blind_annotation
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict

from app.core.config import PROJECT_ROOT

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"

SAMPLE_VERSION = "blind-sample-v2-20260811"

# 固定种子：同一版本重跑必须得到同一批样本，否则导师标注结果无法与样本对齐。
# 换样本时递增版本号并改种子，不原地覆盖（协作规范第 6 节）。
DEFAULT_SEED = 20260811

# 可映射到核心假设的披露类型，配额合计 38。
# 按各类型在总体中的相对规模与业务重要性分配，不按预期方向分配。
QUOTA_RELEVANT: dict[str, int] = {
    "产销数据": 8,
    "定期报告": 6,
    "药品研发进展": 5,
    "药品注册与上市": 4,
    "融资": 4,
    "业绩预告": 3,
    "投资与产能": 3,
    "订单与合同": 2,
    "风险与异动": 2,
    "集采与准入": 1,
}

# 不映射任何假设的类型，配额合计 21。这是"无关提醒率"的分母来源。
QUOTA_NOISE: dict[str, int] = {
    "治理": 6,
    "其他": 5,
    "程式化披露": 4,
    "股权激励": 2,
    "回购与持股变动": 2,
    "担保与关联交易": 2,
}

TOTAL = 59

FIELDS = (
    "序号",
    "公司",
    "证券代码",
    "行业",
    "市场",
    "披露日期",
    "披露时间是否精确",
    "公告标题",
    "原文链接",
    "H1-需求与出货",
    "H2-盈利质量",
    "H3-产能与扩张",
    "关联假设",
    "影响方向",
    "判断理由",
    "标注人",
    "标注时间",
)


def load_hypotheses() -> dict[str, dict]:
    """取每家公司的三条核心假设原文。

    三条假设在 5 个季度的台账里内容完全一致（已校验），因此每家公司只需一套。
    表里逐行冗余写入这三条，是为了让文件**自包含**——导师拿到 CSV 就能判断，
    不需要同时打开 theses.json 对照。
    """
    theses = json.loads((DATASET_DIR / "theses.json").read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for thesis in theses:
        company = thesis["company"]
        if company in out:
            continue
        out[company] = {
            "security_id": thesis["security_id"],
            "contents": {
                h["hypothesis_id"].split("-", 2)[-1].split("-", 1)[-1]: h["content"]
                for h in thesis["hypotheses"]
            },
        }
    return out


def sample(rows: list[dict], seed: int = DEFAULT_SEED) -> list[dict]:
    """分层抽样 59 条：类型定配额，公司均衡，样本内外交替。

    公司均衡是必要的：不做均衡时恒瑞（694 条，占 18%）会按规模主导样本，
    导师会花大半时间在同一家公司的临床批件上，测不出跨行业的判断差异。
    """
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)

    rng = random.Random(seed)
    picked: list[dict] = []
    company_count: Counter[str] = Counter()
    # 同一(公司, 披露日)只取一条。裁决书 6.2：一起资产收购当天可发 7 份文件，
    # 不去重会让 3 个名额只测出 1 个判断，等于把导师的 30 分钟浪费在伪重复上。
    taken_days: set[tuple[str, str]] = set()

    for category, quota in {**QUOTA_RELEVANT, **QUOTA_NOISE}.items():
        pool = sorted(by_category[category], key=lambda r: r["event_id"])
        if len(pool) < quota:
            raise ValueError(f"{category} 仅 {len(pool)} 条，不足配额 {quota}")
        rng.shuffle(pool)
        splits = ("out_of_sample", "in_sample")
        for i in range(quota):
            want = splits[i % 2]

            def day(row: dict) -> tuple[str, str]:
                return row["company"], row["disclosure_time"][:10]

            fresh = [r for r in pool if day(r) not in taken_days]
            candidates = [r for r in fresh if r["split"] == want] or fresh or pool
            # 已抽中次数最少的公司优先；同频次时按随机序先后决定，保证可复现
            chosen = min(candidates, key=lambda r: (company_count[r["company"]], pool.index(r)))
            picked.append(chosen)
            company_count[chosen["company"]] += 1
            taken_days.add(day(chosen))
            pool.remove(chosen)

    if len(picked) != TOTAL:
        raise ValueError(f"抽样得到 {len(picked)} 条，应为 {TOTAL}")

    # 打散呈现顺序：同类型、同公司不成块出现，避免导师按块套用同一判断
    random.Random(seed + 1).shuffle(picked)
    return picked


def write_csv(picked: list[dict], hypotheses: dict[str, dict], out_path) -> None:
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for index, row in enumerate(picked, 1):
            meta = hypotheses[row["company"]]
            precise = row["disclosure_time_precise"] == "True"
            writer.writerow(
                {
                    "序号": index,
                    "公司": row["company"],
                    "证券代码": meta["security_id"],
                    "行业": row["industry"],
                    "市场": row["market"],
                    "披露日期": row["disclosure_time"][:10],
                    # 65.9% 的源时间为 00:00，无法区分盘前盘后，系统一律按盘后。
                    # 标出来让导师知道哪些条目的时点不可精确定位。
                    "披露时间是否精确": "是" if precise else "否（源为00:00，按盘后处理）",
                    "公告标题": row["title"],
                    "原文链接": row["url"],
                    "H1-需求与出货": meta["contents"]["H1-需求与出货"],
                    "H2-盈利质量": meta["contents"]["H2-盈利质量"],
                    "H3-产能与扩张": meta["contents"]["H3-产能与扩张"],
                    "关联假设": "",
                    "影响方向": "",
                    "判断理由": "",
                    "标注人": "",
                    "标注时间": "",
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="抽取独立盲标表")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", default="mentor_blind_annotation_v2.csv")
    args = parser.parse_args()

    with (DATASET_DIR / "events.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    picked = sample(rows, args.seed)
    out_path = DATASET_DIR / args.out
    write_csv(picked, load_hypotheses(), out_path)

    relevant = sum(1 for r in picked if r["category"] in QUOTA_RELEVANT)
    print(f"{SAMPLE_VERSION}: 写入 {out_path}，{len(picked)} 条")
    print(f"  假设映射类 {relevant} / 噪音类 {len(picked) - relevant}")
    print(f"  公司 {dict(Counter(r['company'] for r in picked))}")
    print(f"  行业 {dict(Counter(r['industry'] for r in picked))}")
    print(f"  样本 {dict(Counter(r['split'] for r in picked))}")


if __name__ == "__main__":
    main()
