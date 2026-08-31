"""Prepare the unlabeled Graph-RAG v5 shared-security candidate pool.

Every query for the same security is judged against the same ten public documents.
This mirrors the product's upstream-candidate reranking contract and guarantees that
the benchmark cannot silently treat unjudged same-company documents as irrelevant.
v3/v4 queries and source URLs are excluded before any candidate is selected.
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
from sqlalchemy import create_engine, text

from analytics.pipelines.graph_relevance_v4 import BASE_COLUMNS, _validate_base
from analytics.pipelines.prepare_graph_relevance_v4_pool import (
    CUTOFF,
    CandidateDocument,
    QuerySpec,
    _best_excerpt,
    _download,
    _extract_pages,
    _ordered_candidates,
    _read_csv,
    _retriever,
)
from app.core.config import PROJECT_ROOT, settings

POOL_VERSION = "graph-relevance-v5-shared-security-pool-v1"
CANDIDATES_PER_QUERY = 10
V3_GOLD = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "final-gold-v3-20260826"
    / "final_graph_relevance_gold_v3.csv"
)
V4_GOLD = (
    PROJECT_ROOT / "outputs" / "graph-relevance-v4-final" / "final_graph_relevance_gold_v4.csv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "graph-relevance-v5-blind"
    / "query_candidate_pool.csv"
)
DEFAULT_CACHE = PROJECT_ROOT / ".codex_tmp" / "graph-relevance-v5-source-pdfs"


QUERY_SPECS: tuple[QuerySpec, ...] = (
    QuerySpec("V5-Q001", "002594", "比亚迪", "海外工厂本地化生产能否改善出口业务盈利能力"),
    QuerySpec("V5-Q002", "002594", "比亚迪", "智能驾驶功能投入能否形成车型溢价与软件收入"),
    QuerySpec("V5-Q003", "002594", "比亚迪", "核心零部件垂直整合能否缓冲原材料价格波动"),
    QuerySpec("V5-Q004", "002594", "比亚迪", "区域市场多元化能否降低单一海外市场政策风险"),
    QuerySpec("V5-Q005", "00175", "吉利汽车", "促销与价格折让是否会削弱新能源销量增长的利润贡献"),
    QuerySpec("V5-Q006", "00175", "吉利汽车", "统一架构与研发平台能否降低多品牌车型开发成本"),
    QuerySpec("V5-Q007", "00175", "吉利汽车", "品牌整合产生的一次性成本是否会影响短期盈利质量"),
    QuerySpec("V5-Q008", "09868", "小鹏汽车", "海外本地化销售与服务网络能否改善境外业务规模效应"),
    QuerySpec("V5-Q009", "09868", "小鹏汽车", "AI算力与软件研发投入能否转化为可持续商业化收入"),
    QuerySpec("V5-Q010", "09868", "小鹏汽车", "新平台与生产设施投入是否会延后自由现金流转正"),
    QuerySpec("V5-Q011", "002371", "北方华创", "客户验收周期变化是否会造成订单向收入转化波动"),
    QuerySpec("V5-Q012", "002371", "北方华创", "先进制程设备研发能否扩大高价值产品收入占比"),
    QuerySpec("V5-Q013", "002371", "北方华创", "存货与合同负债变化能否验证在手订单景气度"),
    QuerySpec("V5-Q014", "688981", "中芯国际", "八英寸与十二英寸产品结构变化能否改善综合毛利率"),
    QuerySpec("V5-Q015", "688981", "中芯国际", "设备采购与建设周期是否会降低新增资本开支效率"),
    QuerySpec("V5-Q016", "688981", "中芯国际", "政府补助占比变化是否影响利润的可持续性"),
    QuerySpec("V5-Q017", "688981", "中芯国际", "成熟制程需求结构变化能否支撑新增产能消化"),
    QuerySpec("V5-Q018", "603986", "兆易创新", "车规级MCU渗透能否提升产品组合与客户黏性"),
    QuerySpec("V5-Q019", "603986", "兆易创新", "存货减值与周转变化是否反映存储周期风险"),
    QuerySpec("V5-Q020", "603986", "兆易创新", "DRAM项目资本投入是否会压缩短期现金回报"),
    QuerySpec("V5-Q021", "600276", "恒瑞医药", "海外许可的里程碑与销售分成能否形成持续现金流"),
    QuerySpec("V5-Q022", "600276", "恒瑞医药", "创新药商业化费用增长能否被新品销售规模吸收"),
    QuerySpec("V5-Q023", "600276", "恒瑞医药", "核心临床管线集中度是否放大研发失败风险"),
    QuerySpec("V5-Q024", "600276", "恒瑞医药", "应收账款与回款变化是否影响销售增长的现金质量"),
    QuerySpec("V5-Q025", "603259", "药明康德", "D&M业务新分子项目能否成为订单增长的主要来源"),
    QuerySpec("V5-Q026", "603259", "药明康德", "资本开支节奏是否与自由现金流和产能需求匹配"),
    QuerySpec("V5-Q027", "603259", "药明康德", "客户集中度变化是否影响在手订单兑现稳定性"),
    QuerySpec("V5-Q028", "000538", "云南白药", "健康品渠道改革能否恢复核心品牌销售效率"),
    QuerySpec("V5-Q029", "000538", "云南白药", "药品业务产品结构变化能否提升工业板块毛利率"),
    QuerySpec("V5-Q030", "000538", "云南白药", "投资收益波动是否会影响扣非利润的稳定性"),
)


@dataclass(frozen=True)
class Exclusions:
    query_ids: frozenset[str]
    source_urls: frozenset[str]


def _exclusions() -> Exclusions:
    rows = [*_read_csv(V3_GOLD), *_read_csv(V4_GOLD)]
    return Exclusions(
        query_ids=frozenset(row.get("查询ID", "").strip() for row in rows),
        source_urls=frozenset(
            row.get("候选原文链接", "").strip()
            for row in rows
            if row.get("候选原文链接", "").strip()
        ),
    )


def _load_documents(security_id: str, excluded_urls: frozenset[str]) -> list[CandidateDocument]:
    statement = text(
        """
        SELECT d.document_id, d.security_id, d.title, d.published_at,
               COALESCE(
                   (
                       SELECT r.source_url
                       FROM document_revision r
                       WHERE r.canonical_document_id = d.document_id
                          OR r.document_id = d.document_id
                       ORDER BY r.created_at DESC
                       LIMIT 1
                   ),
                   d.raw_path
               ) AS source_url
        FROM document d
        WHERE d.security_id = :security_id
          AND d.deleted_at IS NULL
          AND d.is_illustrative = false
          AND d.visibility_label = '公开'
          AND d.title IS NOT NULL
          AND d.published_at <= :cutoff
        ORDER BY d.published_at DESC, d.document_id
        """
    )
    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            raw = connection.execute(
                statement, {"security_id": security_id, "cutoff": CUTOFF}
            ).mappings()
            return [
                CandidateDocument(
                    document_id=row["document_id"],
                    security_id=row["security_id"],
                    title=" ".join(str(row["title"]).split()),
                    published_at=row["published_at"],
                    source_url=str(row["source_url"] or "").strip(),
                )
                for row in raw
                if str(row["source_url"] or "").startswith(("http://", "https://"))
                and str(row["source_url"] or "").strip() not in excluded_urls
            ]
    finally:
        engine.dispose()


def _shared_candidate_order(
    specs: list[QuerySpec], documents: list[CandidateDocument]
) -> list[CandidateDocument]:
    retriever = _retriever(documents)
    scores: dict[str, float] = defaultdict(float)
    by_id = {document.document_id: document for document in documents}
    for spec in specs:
        for rank, candidate in enumerate(_ordered_candidates(spec, documents, retriever), start=1):
            scores[candidate.document_id] += 1 / (rank + 4)
    ranked = sorted(
        by_id.values(),
        key=lambda item: (
            -scores[item.document_id],
            -item.published_at.timestamp(),
            item.document_id,
        ),
    )
    recent = sorted(documents, key=lambda item: (-item.published_at.timestamp(), item.document_id))
    financial = [
        item
        for item in ranked
        if any(term in item.title for term in ("年度报告", "半年度报告", "季度报告", "业绩"))
    ]
    governance = [
        item
        for item in ranked
        if any(term in item.title for term in ("股东", "董事会", "关联交易", "关连交易", "章程"))
    ]
    ordered: list[CandidateDocument] = []
    seen: set[str] = set()
    for group, limit in (
        (ranked, 6),
        (financial, 2),
        (governance, 1),
        (recent, None),
        (ranked, None),
    ):
        added = 0
        for item in group:
            if item.document_id in seen:
                continue
            ordered.append(item)
            seen.add(item.document_id)
            added += 1
            if limit is not None and added >= limit:
                break
    return ordered


def prepare_pool(output_path: Path, cache_dir: Path) -> dict[str, Any]:
    exclusions = _exclusions()
    if len(QUERY_SPECS) != 30 or len({spec.query_id for spec in QUERY_SPECS}) != 30:
        raise ValueError("v5 必须包含 30 个唯一查询")
    reused_queries = sorted({spec.query_id for spec in QUERY_SPECS} & exclusions.query_ids)
    if reused_queries:
        raise ValueError(f"v5 查询复用了历史盲测：{reused_queries}")

    specs_by_security: dict[str, list[QuerySpec]] = defaultdict(list)
    for spec in QUERY_SPECS:
        specs_by_security[spec.security_id].append(spec)

    rows: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    page_cache: dict[str, list[tuple[int, str]]] = {}
    selected_by_security: dict[str, list[CandidateDocument]] = {}
    client = httpx.Client(
        follow_redirects=True,
        timeout=45,
        headers={"User-Agent": "Mozilla/5.0 AI-Investment-Copilot-v5-evaluation"},
    )
    try:
        for security_id, specs in sorted(specs_by_security.items()):
            documents = _load_documents(security_id, exclusions.source_urls)
            accepted: list[CandidateDocument] = []
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
                        "关系样本ID": f"V5-R-{spec.query_id.removeprefix('V5-')}-C{candidate_index:02d}",
                        "事件样本ID": f"V5-E-{candidate_key}",
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

    counts = _validate_base(rows, include_v4_exclusions=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BASE_COLUMNS)
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
        "v3_v4_query_reuse": 0,
        "v3_v4_candidate_url_reuse": 0,
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
