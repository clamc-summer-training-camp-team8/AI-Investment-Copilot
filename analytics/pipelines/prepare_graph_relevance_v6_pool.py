"""Prepare the unlabeled Graph-RAG v6 independent blind candidate pool.

Each query for the same security is judged against the same ten public documents.
All v3/v4/v5 query IDs and source URLs are excluded before selection.  The output
contains no relevance labels and is intended to be frozen only after the v6 release
candidate implementation and acceptance thresholds are final.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from analytics.pipelines.graph_relevance_v4 import BASE_COLUMNS, _validate_base
from analytics.pipelines.prepare_graph_relevance_v4_pool import (
    CUTOFF,
    QuerySpec,
    _best_excerpt,
    _download,
    _extract_pages,
    _read_csv,
)
from analytics.pipelines.prepare_graph_relevance_v5_pool import (
    _load_documents,
    _shared_candidate_order,
)
from app.core.config import PROJECT_ROOT

POOL_VERSION = "graph-relevance-v6-shared-security-pool-v1"
CANDIDATES_PER_QUERY = 10
PRIOR_GOLDS = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "final-gold-v3-20260826"
    / "final_graph_relevance_gold_v3.csv",
    PROJECT_ROOT / "outputs" / "graph-relevance-v4-final" / "final_graph_relevance_gold_v4.csv",
    PROJECT_ROOT / "outputs" / "graph-relevance-v5-final" / "final_graph_relevance_gold_v5.csv",
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "graph-relevance-v6-blind"
    / "query_candidate_pool.csv"
)
DEFAULT_CACHE = PROJECT_ROOT / ".codex_tmp" / "graph-relevance-v6-source-pdfs"


QUERY_SPECS: tuple[QuerySpec, ...] = (
    QuerySpec("V6-Q001", "002594", "比亚迪", "动力电池外供与储能业务能否形成第二增长曲线"),
    QuerySpec("V6-Q002", "002594", "比亚迪", "高端车型占比提升能否抵消价格竞争对单车利润的压力"),
    QuerySpec("V6-Q003", "002594", "比亚迪", "经销商库存与应收变化是否会削弱销量增长的现金质量"),
    QuerySpec("V6-Q004", "002594", "比亚迪", "海外产能爬坡期的折旧与费用是否会拖累境外业务利润率"),
    QuerySpec("V6-Q005", "00175", "吉利汽车", "出口区域与海外产能扩张能否改善规模效应和盈利结构"),
    QuerySpec("V6-Q006", "00175", "吉利汽车", "新能源平台研发投入能否通过车型复用降低单位开发成本"),
    QuerySpec("V6-Q007", "00175", "吉利汽车", "批发销量与终端零售差异是否预示渠道库存压力"),
    QuerySpec("V6-Q008", "09868", "小鹏汽车", "大众化车型放量能否在保持毛利率的同时扩大市场份额"),
    QuerySpec("V6-Q009", "09868", "小鹏汽车", "自动驾驶技术服务与授权收入能否降低整车业务周期性"),
    QuerySpec("V6-Q010", "09868", "小鹏汽车", "研发费用与经营现金消耗是否会延后盈亏平衡时点"),
    QuerySpec("V6-Q011", "002371", "北方华创", "关键零部件国产化能否提升设备毛利率和交付稳定性"),
    QuerySpec("V6-Q012", "002371", "北方华创", "外延并购后的整合与商誉变化是否影响盈利质量"),
    QuerySpec("V6-Q013", "002371", "北方华创", "研发投入增长能否转化为刻蚀薄膜等高端设备收入"),
    QuerySpec("V6-Q014", "688981", "中芯国际", "产能利用率变化能否覆盖新增折旧并改善毛利率"),
    QuerySpec("V6-Q015", "688981", "中芯国际", "先进与成熟制程收入结构变化是否提升资本回报效率"),
    QuerySpec("V6-Q016", "688981", "中芯国际", "客户与应用领域集中度是否放大晶圆需求波动风险"),
    QuerySpec("V6-Q017", "688981", "中芯国际", "资本开支融资与汇率变化是否增加自由现金流压力"),
    QuerySpec("V6-Q018", "603986", "兆易创新", "存储产品价格回升能否改善库存周转和综合毛利率"),
    QuerySpec("V6-Q019", "603986", "兆易创新", "高强度研发投入能否扩大MCU与存储产品的收入协同"),
    QuerySpec("V6-Q020", "603986", "兆易创新", "外延投资与项目整合是否会增加商誉和现金流风险"),
    QuerySpec("V6-Q021", "600276", "恒瑞医药", "对外许可首付款确认是否会造成收入与利润阶段性波动"),
    QuerySpec("V6-Q022", "600276", "恒瑞医药", "后期临床项目占比提升能否提高管线上市兑现率"),
    QuerySpec("V6-Q023", "600276", "恒瑞医药", "海外临床与商业化投入能否被国际收入增长覆盖"),
    QuerySpec("V6-Q024", "600276", "恒瑞医药", "研发费用增长与新品放量是否支持长期经营杠杆改善"),
    QuerySpec("V6-Q025", "603259", "药明康德", "海外政策限制是否影响客户订单与产能利用率"),
    QuerySpec("V6-Q026", "603259", "药明康德", "在手订单向收入转化速度能否验证需求恢复"),
    QuerySpec("V6-Q027", "603259", "药明康德", "产能利用率回升能否改善D&M业务毛利率和现金流"),
    QuerySpec("V6-Q028", "000538", "云南白药", "医药商业应收与存货变化是否影响经营现金流质量"),
    QuerySpec("V6-Q029", "000538", "云南白药", "牙膏等健康品增长能否提升核心品牌利润贡献"),
    QuerySpec("V6-Q030", "000538", "云南白药", "投资资产处置与公允价值波动是否影响扣非盈利稳定性"),
)


@dataclass(frozen=True)
class Exclusions:
    query_ids: frozenset[str]
    source_urls: frozenset[str]


def _exclusions() -> Exclusions:
    rows = [row for path in PRIOR_GOLDS for row in _read_csv(path)]
    return Exclusions(
        query_ids=frozenset(row.get("查询ID", "").strip() for row in rows),
        source_urls=frozenset(
            row.get("候选原文链接", "").strip()
            for row in rows
            if row.get("候选原文链接", "").strip()
        ),
    )


def prepare_pool(output_path: Path, cache_dir: Path) -> dict[str, Any]:
    exclusions = _exclusions()
    if len(QUERY_SPECS) != 30 or len({spec.query_id for spec in QUERY_SPECS}) != 30:
        raise ValueError("v6 必须包含 30 个唯一查询")
    reused_queries = sorted({spec.query_id for spec in QUERY_SPECS} & exclusions.query_ids)
    if reused_queries:
        raise ValueError(f"v6 查询复用了历史盲测：{reused_queries}")

    specs_by_security: dict[str, list[QuerySpec]] = defaultdict(list)
    for spec in QUERY_SPECS:
        specs_by_security[spec.security_id].append(spec)

    rows: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    page_cache: dict[str, list[tuple[int, str]]] = {}
    selected_by_security = {}
    client = httpx.Client(
        follow_redirects=True,
        timeout=45,
        headers={"User-Agent": "Mozilla/5.0 AI-Investment-Copilot-v6-evaluation"},
    )
    try:
        for security_id, specs in sorted(specs_by_security.items()):
            documents = _load_documents(security_id, exclusions.source_urls)
            accepted = []
            for candidate in _shared_candidate_order(specs, documents):
                if len(accepted) >= CANDIDATES_PER_QUERY:
                    break
                try:
                    pdf_path = _download(client, candidate, cache_dir)
                    page_cache[candidate.document_id] = _extract_pages(pdf_path)
                    accepted.append(candidate)
                except Exception as exc:
                    failures.append(
                        {
                            "security_id": security_id,
                            "document_id": candidate.document_id,
                            "reason": str(exc)[:240],
                        }
                    )
            if len(accepted) < CANDIDATES_PER_QUERY:
                raise RuntimeError(f"{security_id} 仅取得 {len(accepted)} 个可核验共享候选")
            selected_by_security[security_id] = accepted

        for spec in QUERY_SPECS:
            for candidate_index, candidate in enumerate(
                selected_by_security[spec.security_id], start=1
            ):
                locator, excerpt = _best_excerpt(
                    page_cache[candidate.document_id], spec.hypothesis, candidate.title
                )
                candidate_key = f"{spec.security_id}-C{candidate_index:02d}"
                rows.append(
                    {
                        "关系样本ID": f"V6-R-{spec.query_id.removeprefix('V6-')}-C{candidate_index:02d}",
                        "事件样本ID": f"V6-E-{candidate_key}",
                        "查询ID": spec.query_id,
                        "公司": spec.company,
                        "证券代码": spec.security_id,
                        "检索截止时间": CUTOFF.isoformat(),
                        "查询假设": spec.hypothesis,
                        "候选文档ID": candidate.document_id,
                        "候选公告标题": candidate.title,
                        "候选发布日期": candidate.published_at.isoformat(),
                        "候选原文链接": candidate.source_url,
                        "关键证据定位": locator,
                        "关键证据原文": excerpt,
                    }
                )
    finally:
        client.close()

    counts = _validate_base(
        rows,
        include_v4_exclusions=True,
        include_v5_exclusions=True,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=BASE_COLUMNS,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    manifest: dict[str, Any] = {
        "schema_version": POOL_VERSION,
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "cutoff": CUTOFF.isoformat(),
        "candidate_scope": "shared_security_closed_pool",
        "queries": len(counts),
        "rows": len(rows),
        "candidates_per_query": sorted(set(counts.values())),
        "companies": len(specs_by_security),
        "source_documents": len({row["候选文档ID"] for row in rows}),
        "v3_v4_v5_query_reuse": 0,
        "v3_v4_v5_candidate_url_reuse": 0,
        "label_columns_written": False,
        "download_or_parse_failures_skipped": failures,
    }
    output_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    print(json.dumps(prepare_pool(args.output, args.cache_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
