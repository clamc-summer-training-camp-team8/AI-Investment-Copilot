"""从公告构建事件样本与预标注。

**这里产出的是「程序化预标注」，不是金标。** 说明书第 12 节要求金标由研究员或具备
金融业务判断能力的导师确认，GAP-004（金标负责人与裁决机制）至今未关闭。把程序生成
的标签叫金标，等于用一个程序去评测另一个程序，评测结论没有意义。

因此本模块的定位是：**把样本组织好、把规则不清楚的地方找出来，交给导师确认。**
这正是数据分析师在说明书 12 节里的职责（样本组织、版本管理、一致性统计）。

为避免评测循环，三套判断刻意用不同的信息与规则：

| 角色 | 依据 | 实现位置 |
| --- | --- | --- |
| 标注者 A | 公告类型的监管语义（定期报告/产销/融资…） | 本模块 `annotate_by_category` |
| 标注者 B | 业务动作语义（增/减、达成/终止、扩张/收缩） | 本模块 `annotate_by_action` |
| 关键词基线 | 单一词表命中 | `analytics/evaluation/baseline.py` |
| AI | app/ai 的 local 提供者 | `app/ai/providers/local.py` |

A 与 B 的一致率（Cohen's kappa）用来回答「标注规则是否清晰」，不一致的样本进入
裁决队列。说明书要求首批双人标注不少于 20% 样本，这里对全部样本都做，因为程序化
标注的边际成本为零，没有理由只做 20%。

用法：
    python -m analytics.pipelines.annotate_events
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from app.core.config import PROJECT_ROOT
from app.core.enums import ImpactDirection

RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
OUT_DIR = PROJECT_ROOT / "real_data" / "dataset"

ANNOTATION_VERSION = "pre-annotation-v2"

# 港交所与交易所要求的程式化公告。它们按月按次机械发布，不含经营信息。
# 必须**最先**排除，原因有两个：
# 1. 「H股公告」这类前缀会被融资规则的 `H股` 命中。实测样本内 361 条「融资」里
#    304 条含「H股」字样，其中绝大多数是证券变动月报表与翌日披露报表——
#    把法定月报表当成融资事件，等于给 H3 假设灌了一堆假证据。
# 2. 「月报表截至31/7/2026」是港股证券变动月报，不是销量月报。名字像销量数据，
#    实际与经营无关，必须在产销规则之前排除。
PROCEDURAL_NOISE = (
    r"翌日披露报表"
    r"|证券变动月报表"
    r"|月报表截至"
    r"|通知信函"
    r"|公司通讯"
    r"|董事名单与其角色"
    r"|暂停办理"
    r"|过户登记"
    r"|股东周年大会"
    r"|表决结果"
    r"|受托管理事务"
    r"|存续期"
    r"|跟踪评级"
    r"|付息|兑付"
)

# 事件类型：按监管披露语义划分，与标题关键词无关。
# 顺序敏感：越具体的行业事件放越前面，通用规则兜后。
CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    # —— 医药行业专属：研发与准入是这个行业最主要的价值事件 ——
    # 恒瑞样本内有 128 条临床试验批准公告，原规则全部归入「其他」，
    # 等于把创新药公司最核心的信号丢掉。
    ("药品研发进展", r"临床试验|临床研究|突破性治疗|优先审评|快速通道|孤儿药|IND|新药研究"),
    ("药品注册与上市", r"注册证书|注册批准|上市许可|获准上市|生产批件|上市申请.{0,6}受理|补充申请"),
    ("集采与准入", r"集中采购|带量采购|集采|医保目录|挂网|中选结果|谈判结果"),
    ("药品质量与合规", r"GMP|飞行检查|药品召回|不良反应|一致性评价"),
    # —— 半导体行业专属 ——
    ("产能与制程进展", r"晶圆|制程|流片|封测|良率|产线|N\+1|先进封装"),
    # —— 汽车行业专属：销量与交付是最高频的经营数据 ——
    ("产销数据", r"产销快报|产销数据|经营数据|交付数据|销量(?!目标)|交付量|上险"),
    # —— 通用监管类型 ——
    ("定期报告", r"年度报告|半年度报告|季度报告|年报|中报|业绩公布|业绩公告|中期业绩"),
    ("业绩预告", r"业绩预告|业绩快报|盈利警告|正面盈利预告"),
    ("订单与合同", r"中标|签订|订单|重大合同|框架协议|战略合作|采购协议|供货"),
    ("投资与产能", r"对外投资|投资设立|扩产|产能|建设项目|新建|增资|收购|合营公司"),
    ("融资", r"募集资金|定向增发|可转债|存托凭证|发行.{0,6}股份|配股|供股|中期票据"),
    ("股权激励", r"限制性股票|股票期权|员工持股|限制性股份单位"),
    ("回购与持股变动", r"回购|增持|减持|股份.{0,4}变动|权益变动|质押|解除质押"),
    ("担保与关联交易", r"提供担保|担保额度|关联交易|持续关连交易"),
    ("风险与异动", r"股价异动|风险提示|诉讼|仲裁|处罚|减值|问询|立案|终止|撤回"),
    (
        "治理",
        r"制度|章程|议事规则|决议公告|独立董事|监事|董事会|股东大会|换届|利润分配|会计政策|审计|内部控制|ESG|环境、社会",
    ),
)

# 与三条核心假设的对应关系。一条证据只关联一个假设：
# 关联多个假设会让方向判断失去可检验性（一条证据同时支持又冲突无法验证）。
#
# 跨行业时假设骨架保持一致（H1 需求与出货 / H2 盈利质量 / H3 产能与扩张），
# 但落到各行业的事件类型不同：
# - 医药的研发进展与注册上市是未来收入的来源，归 H1（需求与出货）而不是 H3，
#   因为它决定的是「有没有东西可卖」，不是「能不能造出来」。
# - 集采与准入直接压价，归 H2（盈利质量）。这是医药行业最典型的利润冲击事件。
# - 半导体的制程与产能进展归 H3。
CATEGORY_TO_HYPOTHESIS: dict[str, str] = {
    "定期报告": "H2-盈利质量",
    "业绩预告": "H2-盈利质量",
    "产销数据": "H1-需求与出货",
    "订单与合同": "H1-需求与出货",
    "药品研发进展": "H1-需求与出货",
    "药品注册与上市": "H1-需求与出货",
    "集采与准入": "H2-盈利质量",
    "药品质量与合规": "H2-盈利质量",
    "产能与制程进展": "H3-产能与扩张",
    "投资与产能": "H3-产能与扩张",
    "融资": "H3-产能与扩张",
    "风险与异动": "H2-盈利质量",
}

# 不影响任何核心假设的类型。这些是"无关提醒率"的分母来源，
# 不能从样本里删掉——删掉就等于把最容易误报的部分藏起来（选择偏差）。
NON_THESIS_CATEGORIES = frozenset(
    {"股权激励", "回购与持股变动", "担保与关联交易", "治理", "程式化披露", "其他"}
)

# 业务动作词表，标注者 B 用。刻意与关键词基线的词表不同：
# B 看的是方向性动作词，基线看的是主题词。
POSITIVE_ACTIONS = (
    "增长",
    "增加",
    "提高",
    "提升",
    "中标",
    "签订",
    "达成",
    "投产",
    "扩产",
    "增资",
    "盈利",
    "扭亏",
    "创新高",
)
# 刻意**不**加「获得/获批/批准/受理」这些词。它们看起来是正向动作词，但在医药样本里
# 与「药品研发进展」「药品注册与上市」两个类型几乎完全重合（316 条里 315 条命中）。
# 加进去会让 B 在这些样本上必然与 A 一致，方向 kappa 从 0.52 虚假抬到 0.89——
# 抬上去的不是规则清晰度，是两个标注者的相关性。两名标注者必须保持独立，
# 否则一致性指标就不再衡量任何东西（和原来 hypothesis_kappa 恒为 1.0 是同一类错误）。
#
# 保留这个分歧反而有价值：「拿到临床试验批准算不算支持需求假设的证据」
# 正是需要业务导师裁决的真问题，它会出现在待裁决队列里。
NEGATIVE_ACTIONS = (
    "下降",
    "减少",
    "下滑",
    "亏损",
    "终止",
    "解除",
    "延期",
    "减值",
    "处罚",
    "诉讼",
    "问询",
    "立案",
    "风险提示",
    "预减",
    "预亏",
    # 港股业绩预警。这个词与类型不重合（盈利警告是定期报告/业绩预告类下的方向词），
    # 加它不会造成 A、B 相关，反而补上了 B 原来读不出港股预警的空白。
    "盈利警告",
)


@dataclass
class EventSample:
    """一条事件样本。

    `disclosure_time_precise` 记录披露时间是否带具体时刻。巨潮有 66% 的公告时间是
    00:00，无法区分盘前盘后。这个字段让下游能对这部分样本做保守处理，而不是假装
    知道确切时点。
    """

    event_id: str
    security_id: str
    company: str
    industry: str
    market: str
    title: str
    disclosure_time: str
    disclosure_time_precise: bool
    category: str
    annotator_a_hypothesis: str
    annotator_a_direction: str
    annotator_b_hypothesis: str
    annotator_b_direction: str
    agreed: bool
    needs_adjudication: bool
    split: str = ""
    url: str = ""


def classify_category(title: str) -> str:
    """按监管披露语义分类。顺序敏感：先匹配到的胜出。

    两层前置排除，都是为了不让「形似」的标题污染业务类型：

    1. 会议类。「年度报告网上说明会」同时含「年度报告」和「说明会」，归定期报告是错的
       ——它不含财务数据。
    2. 程式化披露。港交所的翌日披露报表、证券变动月报表按期机械发布，
       不含经营信息。它们单独成类而不是塞进「其他」，因为「其他」是兜底类，
       混进大量已知无关项会让无关提醒率的分母失去意义。
    """
    if re.search(r"说明会|网上互动|路演|接待|调研", title):
        return "治理"
    if re.search(PROCEDURAL_NOISE, title):
        return "程式化披露"
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, title):
            return name
    return "其他"


def annotate_by_category(title: str, category: str) -> tuple[str, str]:
    """标注者 A：只看公告类型的监管语义，不读标题里的方向词。

    方向判断：定期报告与业绩预告需要看是增是减，其余类型按该类型的一般业务含义给
    默认方向。拿不准就给中性——强行归类会制造错误的证据方向（标注规范 §4）。
    """
    hypothesis = CATEGORY_TO_HYPOTHESIS.get(category, "")
    if not hypothesis:
        return "", ImpactDirection.IRRELEVANT.value

    if category in ("定期报告", "业绩预告"):
        if re.search(r"预增|增长|上升|扭亏|盈利(?!警告)|正面盈利预告", title):
            return hypothesis, ImpactDirection.SUPPORT.value
        if re.search(r"预减|预亏|下降|下滑|亏损|盈利警告", title):
            return hypothesis, ImpactDirection.CONFLICT.value
        # 定期报告本身不含方向，要读正文才知道。标为中性并进人工队列。
        return hypothesis, ImpactDirection.NEUTRAL.value

    if category == "风险与异动":
        return hypothesis, ImpactDirection.CONFLICT.value

    if category == "集采与准入":
        # 集采是医药行业的双向事件：中选保住了销量但通常大幅降价，
        # 落选则直接丢失院内市场。方向取决于降价幅度与放量的相对大小，
        # 标题读不出来。这类必须进人工队列——机器替它拍方向就是制造假证据。
        return hypothesis, ImpactDirection.NEUTRAL.value

    if category == "药品质量与合规":
        return hypothesis, ImpactDirection.CONFLICT.value

    if category in ("药品研发进展", "药品注册与上市"):
        # 获批/受理是研发管线推进，对未来收入是正向。撤回或终止另有风险类型接管。
        return hypothesis, ImpactDirection.SUPPORT.value

    if category in ("订单与合同", "投资与产能", "产能与制程进展"):
        return hypothesis, ImpactDirection.SUPPORT.value

    if category == "产销数据":
        # 「2026年7月产销快报」只说明有这份数据，说不出是增是减。
        # 原来把产销数据一律判为支持是错的：销量下滑的月报也会被判成支持。
        return hypothesis, ImpactDirection.NEUTRAL.value

    if category == "融资":
        # 融资对产能扩张是支持，对每股权益是摊薄。业务上以扩张为主判断。
        return hypothesis, ImpactDirection.SUPPORT.value
    return hypothesis, ImpactDirection.NEUTRAL.value


def annotate_by_action(title: str, category: str) -> tuple[str, str]:
    """标注者 B：只看方向性动作词，独立判断是否影响假设。

    与 A 的差别是刻意的：B 认为「没有明确方向动作词的公告不构成可判断的证据」，
    这是一种更保守的标注立场。两者的分歧点正是规则需要澄清的地方。
    """
    positive = sum(1 for w in POSITIVE_ACTIONS if w in title)
    negative = sum(1 for w in NEGATIVE_ACTIONS if w in title)

    if category in NON_THESIS_CATEGORIES:
        return "", ImpactDirection.IRRELEVANT.value

    hypothesis = CATEGORY_TO_HYPOTHESIS.get(category, "")
    if not hypothesis:
        return "", ImpactDirection.IRRELEVANT.value

    if positive and negative:
        return hypothesis, ImpactDirection.NEUTRAL.value
    if negative:
        return hypothesis, ImpactDirection.CONFLICT.value
    if positive:
        return hypothesis, ImpactDirection.SUPPORT.value
    return hypothesis, ImpactDirection.NEUTRAL.value


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa。衡量两名标注者扣除偶然一致后的一致程度。

    只报观察一致率会高估：大量样本都是「无关」，随便标都能对上。
    """
    if not pairs:
        return 0.0
    total = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / total

    labels = {label for pair in pairs for label in pair}
    expected = 0.0
    for label in labels:
        pa = sum(1 for a, _ in pairs if a == label) / total
        pb = sum(1 for _, b in pairs if b == label) / total
        expected += pa * pb

    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def build(split_date: str = "2025-10-01") -> tuple[list[EventSample], dict[str, object]]:
    """构建样本。按时间切分样本内外（说明书 10.2 第 4 步）。

    切分点 2025-10-01 是**在看任何结果之前**定的，取「留出最后约 10 个月做样本外」
    这个朴素规则，不是调出来的。样本外区间还要留足 20 个交易日的收益窗口。
    """
    raw = json.loads((RAW_DIR / "announcements.json").read_text(encoding="utf-8"))
    samples: list[EventSample] = []
    # 序号按公司独立计数。原来用全局 enumerate，导致 event_id 里的证券代码
    # 与序号完全无关（EVT-002594-00001 后面接 EVT-300750-00002），看着像错位。
    counters: Counter[str] = Counter()

    for item in raw:
        title = item["title"]
        category = classify_category(title)
        a_hypothesis, a_direction = annotate_by_category(title, category)
        b_hypothesis, b_direction = annotate_by_action(title, category)

        agreed = (a_hypothesis, a_direction) == (b_hypothesis, b_direction)
        disclosure = item["disclosure_time"]
        security_id = item["security_id"]
        counters[security_id] += 1

        samples.append(
            EventSample(
                event_id=f"EVT-{security_id}-{counters[security_id]:05d}",
                security_id=security_id,
                company=item["company"],
                industry=item.get("industry", ""),
                market=item.get("market", ""),
                title=title,
                disclosure_time=disclosure,
                disclosure_time_precise=disclosure[11:16] != "00:00",
                category=category,
                annotator_a_hypothesis=a_hypothesis,
                annotator_a_direction=a_direction,
                annotator_b_hypothesis=b_hypothesis,
                annotator_b_direction=b_direction,
                agreed=agreed,
                needs_adjudication=not agreed,
                split="in_sample" if disclosure[:10] < split_date else "out_of_sample",
                url=item.get("url", ""),
            )
        )

    direction_pairs = [(s.annotator_a_direction, s.annotator_b_direction) for s in samples]
    hypothesis_pairs = [(s.annotator_a_hypothesis, s.annotator_b_hypothesis) for s in samples]

    stats: dict[str, object] = {
        "annotation_version": ANNOTATION_VERSION,
        "total": len(samples),
        "split_date": split_date,
        "in_sample": sum(1 for s in samples if s.split == "in_sample"),
        "out_of_sample": sum(1 for s in samples if s.split == "out_of_sample"),
        "thesis_relevant": sum(1 for s in samples if s.annotator_a_hypothesis),
        "needs_adjudication": sum(1 for s in samples if s.needs_adjudication),
        "direction_kappa": round(cohen_kappa(direction_pairs), 4),
        "hypothesis_kappa": round(cohen_kappa(hypothesis_pairs), 4),
        "direction_observed_agreement": round(
            sum(1 for a, b in direction_pairs if a == b) / len(direction_pairs), 4
        ),
        "category_counts": dict(Counter(s.category for s in samples).most_common()),
        "imprecise_time_count": sum(1 for s in samples if not s.disclosure_time_precise),
    }

    # 分行业统计。跨行业混在一起看总数会掩盖某个行业样本不足的问题：
    # 一致性 kappa 也要分行业看，因为标注规则的清晰程度在三个行业里并不相同。
    by_industry: dict[str, object] = {}
    for industry in sorted({s.industry for s in samples if s.industry}):
        subset = [s for s in samples if s.industry == industry]
        pairs = [(s.annotator_a_direction, s.annotator_b_direction) for s in subset]
        by_industry[industry] = {
            "total": len(subset),
            "thesis_relevant": sum(1 for s in subset if s.annotator_a_hypothesis),
            "in_sample": sum(1 for s in subset if s.split == "in_sample"),
            "out_of_sample": sum(1 for s in subset if s.split == "out_of_sample"),
            "needs_adjudication": sum(1 for s in subset if s.needs_adjudication),
            "direction_kappa": round(cohen_kappa(pairs), 4),
            "imprecise_time_count": sum(1 for s in subset if not s.disclosure_time_precise),
        }
    stats["by_industry"] = by_industry

    by_company: dict[str, object] = {}
    for company in sorted({s.company for s in samples}):
        subset = [s for s in samples if s.company == company]
        by_company[company] = {
            "total": len(subset),
            "thesis_relevant": sum(1 for s in subset if s.annotator_a_hypothesis),
        }
    stats["by_company"] = by_company

    return samples, stats


def write(samples: list[EventSample], stats: dict[str, object]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    events_path = OUT_DIR / "events.csv"
    with events_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(vars(samples[0]).keys()))
        writer.writeheader()
        for sample in samples:
            writer.writerow(vars(sample))

    adjudication = [s for s in samples if s.needs_adjudication]
    adjudication_path = OUT_DIR / "adjudication_queue.csv"
    with adjudication_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "event_id",
                "company",
                "title",
                "category",
                "annotator_a_hypothesis",
                "annotator_a_direction",
                "annotator_b_hypothesis",
                "annotator_b_direction",
            ],
        )
        writer.writeheader()
        for sample in adjudication:
            writer.writerow(
                {
                    k: getattr(sample, k)
                    for k in (
                        "event_id",
                        "company",
                        "title",
                        "category",
                        "annotator_a_hypothesis",
                        "annotator_a_direction",
                        "annotator_b_hypothesis",
                        "annotator_b_direction",
                    )
                }
            )

    stats["generated_at"] = datetime.now().astimezone().isoformat()
    (OUT_DIR / "annotation_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"事件样本 {len(samples)} 条 → {events_path}")
    print(f"待裁决 {len(adjudication)} 条 → {adjudication_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-date", default="2025-10-01")
    args = parser.parse_args()

    samples, stats = build(args.split_date)
    write(samples, stats)

    print()
    print("标注一致性（说明书 12：用于检查规则是否清晰）")
    print(f"  方向观察一致率  {stats['direction_observed_agreement']}")
    print(f"  方向 kappa      {stats['direction_kappa']}")
    print(f"  假设 kappa      {stats['hypothesis_kappa']}")
    print(f"  待裁决          {stats['needs_adjudication']} / {stats['total']}")
    print()
    print(f"影响核心假设的事件  {stats['thesis_relevant']} 条")
    print(f"样本内 / 样本外     {stats['in_sample']} / {stats['out_of_sample']}")
    print(f"披露时间无具体时刻  {stats['imprecise_time_count']} 条（需保守处理）")


if __name__ == "__main__":
    main()
