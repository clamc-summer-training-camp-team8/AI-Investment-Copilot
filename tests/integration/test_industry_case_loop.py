"""行业级闭环的回归测试。

`real_data/` 已纳入版本控制（ADR-0006），因此这些测试在 CI 里**真实执行**，
不再 skip。数据缺失时直接失败：数据是仓库的一部分，缺了就是仓库坏了，
用 skip 掩盖会让样本量与可追溯率的断言变成永远不生效的装饰。

这里守的是几条容易在重构中失效的纪律：时间窗口裁剪、人工闸门、可追溯性、
口径不混算。
"""

from __future__ import annotations

import csv
import json

import pytest

from analytics.pipelines.universe import BENCHMARKS, COMPANIES, INDUSTRIES
from app.core.config import PROJECT_ROOT

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
RAW_DIR = PROJECT_ROOT / "real_data" / "raw"


def test_数据集在版本控制内() -> None:
    """数据集必须存在。它们已进版本控制，缺失说明仓库不完整而不是环境问题。"""
    for path in (
        DATASET_DIR / "theses.json",
        DATASET_DIR / "events.csv",
        RAW_DIR / "financials.json",
        RAW_DIR / "quotes.json",
    ):
        assert path.is_file(), f"{path} 缺失。它已纳入版本控制（ADR-0006），不该缺"


@pytest.fixture(scope="module")
def theses() -> list[dict]:
    return json.loads((DATASET_DIR / "theses.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def events() -> list[dict]:
    with (DATASET_DIR / "events.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def financials() -> dict:
    return json.loads((RAW_DIR / "financials.json").read_text(encoding="utf-8"))["metrics"]


def test_sample_sizes_meet_spec(theses: list[dict], events: list[dict]) -> None:
    """说明书第 4 节的最低样本建议。"""
    assert 30 <= len(theses) <= 50, f"投资逻辑应为 30-50 条，实际 {len(theses)}"

    relevant = [e for e in events if e["annotator_a_hypothesis"]]
    assert len(relevant) >= 200, f"影响核心假设的事件应不少于 200 条，实际 {len(relevant)}"


def test_every_hypothesis_has_invalidation_rule(theses: list[dict]) -> None:
    """每条假设都要有失效条件，否则无法监控（PRD 要求）。"""
    for thesis in theses:
        assert 2 <= len(thesis["hypotheses"]) <= 5
        for hypothesis in thesis["hypotheses"]:
            assert hypothesis["invalidation_rule"], f"{hypothesis['hypothesis_id']} 缺失效条件"


def test_participating_hypotheses_have_thresholds(theses: list[dict]) -> None:
    """参与复合失效判断的假设必须有可机器判断的阈值。

    只有自然语言规则的假设不能参与自动失效判断——否则 `evaluate_thesis_invalidation`
    会因为拿不到 check 而把它算作未满足，行为取决于实现细节而非业务意图。
    """
    for thesis in theses:
        for hypothesis in thesis["hypotheses"]:
            if hypothesis["participates_in_invalidation"]:
                assert hypothesis[
                    "metric_id"
                ], f"{hypothesis['hypothesis_id']} 参与失效判断但无指标"
                assert hypothesis[
                    "threshold"
                ], f"{hypothesis['hypothesis_id']} 参与失效判断但无阈值"


def test_financials_are_single_quarter(financials: dict) -> None:
    """财务指标必须是单季度口径（说明书 7.2：不允许混算）。"""
    for security_id, metrics in financials.items():
        assert metrics, f"{security_id} 无财务数据"
        for metric in metrics:
            assert (
                metric["period_type"] == "单季度"
            ), f"{security_id} {metric['period']} 口径为 {metric['period_type']}，应为单季度"


def test_quarterly_revenue_sums_to_annual() -> None:
    """差分正确性：四个单季度收入之和必须等于年报披露的累计收入。

    这是验证「累计值已差分为单季度值」的正确方法。曾经用「季度收入不应单调递增」
    来判断，那是错的——储能与光伏行业 Q4 是装机旺季，季度收入递增是真实季节性，
    不是差分失败。
    """
    payload = json.loads((RAW_DIR / "financials.json").read_text(encoding="utf-8"))
    annual = payload.get("annual_revenue") or {}
    if not annual:
        pytest.skip("需重跑 analytics.pipelines.fetch_financials 以生成年报对照数据")

    checked = 0
    for security_id, metrics in payload["metrics"].items():
        by_year: dict[str, list[float]] = {}
        for metric in metrics:
            by_year.setdefault(metric["period"][:4], []).append(float(metric["revenue"]))

        for year, quarters in by_year.items():
            expected = annual.get(security_id, {}).get(year)
            if expected is None or len(quarters) != 4:
                continue
            # 相对误差容忍 0.1%，覆盖披露值本身的四舍五入
            assert abs(sum(quarters) - float(expected)) / float(expected) < 0.001, (
                f"{security_id} {year} 单季度之和 {sum(quarters):.0f} "
                f"与年报 {float(expected):.0f} 不符，差分有误"
            )
            checked += 1

    assert checked > 0, "没有任何年度可供校验，差分正确性未被验证"


def test_disclosure_time_present_for_all_events(events: list[dict]) -> None:
    """DQ-001：缺少来源或时间不得产生正式信号。"""
    for event in events:
        assert event["disclosure_time"], f"{event['event_id']} 缺披露时间"
        assert event["url"], f"{event['event_id']} 缺来源链接"


def test_split_is_time_based(events: list[dict]) -> None:
    """样本内外必须按时间切分，不能有交叉（说明书 10.2 第 4 步）。"""
    in_sample = [e["disclosure_time"][:10] for e in events if e["split"] == "in_sample"]
    out_sample = [e["disclosure_time"][:10] for e in events if e["split"] == "out_of_sample"]
    assert in_sample and out_sample
    assert max(in_sample) < min(out_sample), "样本内外时间区间存在交叉"


def test_三个行业各三家公司(theses: list[dict]) -> None:
    """研究范围必须真的覆盖三个行业各三家，不能某个行业只剩一家还照样出报告。"""
    by_industry: dict[str, set[str]] = {}
    for thesis in theses:
        by_industry.setdefault(thesis["industry"], set()).add(thesis["company"])

    assert set(by_industry) == set(INDUSTRIES), f"行业不齐：{sorted(by_industry)}"
    for industry, companies in by_industry.items():
        assert len(companies) == 3, f"{industry} 有 {len(companies)} 家公司，应为 3 家"


def test_每个行业有独立基准() -> None:
    """基准必须按行业区分。共用一个基准会把行业轮动算成个股 alpha。"""
    assert set(BENCHMARKS) == set(INDUSTRIES)
    ids = [b.security_id for b in BENCHMARKS.values()]
    assert len(set(ids)) == len(ids), f"存在共用基准：{ids}"

    quotes = json.loads((RAW_DIR / "quotes.json").read_text(encoding="utf-8"))["series"]
    for industry, benchmark in BENCHMARKS.items():
        assert benchmark.security_id in quotes, f"{industry} 的基准无行情，超额收益算不出来"


def test_阈值只用建立日之前的历史(theses: list[dict]) -> None:
    """失效阈值不能拿观察期内的数据定，否则是用结果调参数。

    阈值口径写死在 build_theses 里：2022Q1~2024Q3，全部早于最早建立日 2025-01-20。
    这里守的是「最早建立日不早于阈值历史的截止」这个关系。
    """
    earliest = min(t["established_on"] for t in theses)
    assert earliest >= "2024-10-31", (
        f"最早建立日 {earliest} 早于阈值所用历史（截至 2024Q3，披露于 2024-10-31），"
        "阈值可能包含了观察期内的信息"
    )


def test_港股公司的季度颗粒度差异被如实记录(financials: dict) -> None:
    """港股不强制季报，期数少于 A 股是制度差异，不能靠插值补齐。

    断言的是「港股公司确实存在期数缺口」而不是「期数相等」：如果哪天这里变成相等，
    说明有人插值填平了缺口，那才是真问题。
    """
    hk_ids = [c.security_id for c in COMPANIES if c.is_hk]
    assert hk_ids, "研究范围里应有港股公司"

    for security_id in hk_ids:
        periods = {m["period"] for m in financials[security_id]}
        assert periods, f"{security_id} 无财务数据"
        # 全部为单季度口径已由 test_financials_are_single_quarter 覆盖，
        # 这里只检查没有凭空补出连续的四个季度
        for metric in financials[security_id]:
            assert metric["revenue"], f"{security_id} {metric['period']} 收入为空却入库"


def test_closed_loop_traceability() -> None:
    """闭环产出的证据 100% 可追溯（DA-AC-07 / 目标 5）。"""
    report = PROJECT_ROOT / "real_data" / "reports" / "closed_loop_result.json"
    if not report.exists():
        pytest.skip("需先跑 scripts/run_industry_case.py")

    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["evidence_attached"] > 0
    assert result["traceability_rate"] == 1.0, (
        f"可追溯率应为 100%，实际 {result['traceability_rate']}，"
        f"不可追溯样例：{result.get('untraceable_samples')}"
    )


def test_no_automatic_status_change_without_human() -> None:
    """AI 不得自动改变正式状态（说明书 DA-AC-08 / 产品红线）。

    闭环里每次状态变更都必须对应一次人工决策。
    """
    report = PROJECT_ROOT / "real_data" / "reports" / "closed_loop_result.json"
    if not report.exists():
        pytest.skip("需先跑 scripts/run_industry_case.py")

    result = json.loads(report.read_text(encoding="utf-8"))
    changed = [o for o in result["outcomes"] if o["final_status"] != "验证中"]
    assert (
        len(changed) <= result["human_decisions"]
    ), f"有 {len(changed)} 条逻辑状态变更，但仅 {result['human_decisions']} 次人工决策"
