"""Prepare the unlabeled Graph-RAG v4 candidate pool from public disclosures.

The script deliberately uses only query text and public source text.  It excludes every
v3 query ID and source URL, never reads a v3 relevance/path label, and writes no v4 label
column.  Professional researchers remain responsible for every relevance judgement.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pypdf import PdfReader
from sqlalchemy import create_engine, text

from analytics.pipelines.graph_relevance_v4 import BASE_COLUMNS, _validate_base
from app.ai.retrieval import (
    AnnouncementTypePriorRetriever,
    BM25Retriever,
    CandidateUnionRetriever,
    ChineseVectorRetriever,
    DiversityReranker,
    KeywordRetriever,
    RetrievalDocument,
    RetrievalQuery,
    tokenize_zh_terms,
)
from app.core.config import PROJECT_ROOT, settings

POOL_VERSION = "graph-relevance-v4-candidate-pool-v1"
CUTOFF = datetime(2026, 8, 26, 18, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
V3_GOLD = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "final-gold-v3-20260826"
    / "final_graph_relevance_gold_v3.csv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "graph-relevance-v4-blind"
    / "query_candidate_pool.csv"
)
DEFAULT_CACHE = PROJECT_ROOT / ".codex_tmp" / "graph-relevance-v4-source-pdfs"


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    security_id: str
    company: str
    hypothesis: str


@dataclass(frozen=True)
class CandidateDocument:
    document_id: str
    security_id: str
    title: str
    published_at: datetime
    source_url: str


# These are new decision-oriented questions, not rewrites of the three v3 hypotheses per
# company.  Query construction is visible and frozen; only the professional labels are blind.
QUERY_SPECS: tuple[QuerySpec, ...] = (
    QuerySpec("V4-Q001", "002594", "比亚迪", "海外销量增长能否持续抵消国内价格竞争对收入的压力"),
    QuerySpec("V4-Q002", "002594", "比亚迪", "高端车型与产品结构升级能否改善汽车业务单车盈利"),
    QuerySpec(
        "V4-Q003", "002594", "比亚迪", "动力电池与储能业务能否形成汽车业务之外的第二增长曲线"
    ),
    QuerySpec("V4-Q004", "002594", "比亚迪", "销量扩张过程中库存与经营现金流能否保持健康"),
    QuerySpec("V4-Q005", "00175", "吉利汽车", "新能源车型渗透率提升能否持续改善销量结构"),
    QuerySpec("V4-Q006", "00175", "吉利汽车", "出口销量增长能否成为吉利汽车的稳定增量来源"),
    QuerySpec("V4-Q007", "00175", "吉利汽车", "极氪与领克渠道协同能否转化为销售效率提升"),
    QuerySpec("V4-Q008", "09868", "小鹏汽车", "新车型上市后的交付放量能否推动季度销量持续增长"),
    QuerySpec("V4-Q009", "09868", "小鹏汽车", "与大众汽车的技术合作能否形成可持续的技术服务收入"),
    QuerySpec("V4-Q010", "09868", "小鹏汽车", "智能驾驶研发投入能否转化为产品差异化与毛利改善"),
    QuerySpec("V4-Q011", "002371", "北方华创", "半导体设备订单增长能否持续转化为营业收入"),
    QuerySpec("V4-Q012", "002371", "北方华创", "国产替代能否推动高端半导体设备品类持续扩张"),
    QuerySpec("V4-Q013", "002371", "北方华创", "扩产与研发投入是否会显著挤压短期经营现金流"),
    QuerySpec("V4-Q014", "688981", "中芯国际", "新增晶圆产能释放能否持续带动收入增长"),
    QuerySpec("V4-Q015", "688981", "中芯国际", "产能利用率回升能否推动晶圆代工毛利率改善"),
    QuerySpec("V4-Q016", "688981", "中芯国际", "资本开支与新增折旧压力能否被下游需求增长消化"),
    QuerySpec("V4-Q017", "688981", "中芯国际", "外部贸易限制是否会影响先进产能建设与客户需求"),
    QuerySpec("V4-Q018", "603986", "兆易创新", "DRAM募投项目能否形成新的收入贡献"),
    QuerySpec("V4-Q019", "603986", "兆易创新", "存储芯片价格与库存周期改善能否提升盈利能力"),
    QuerySpec("V4-Q020", "603986", "兆易创新", "研发投入能否支持MCU与存储产品持续升级"),
    QuerySpec("V4-Q021", "600276", "恒瑞医药", "创新药获批数量增长能否转化为销售放量"),
    QuerySpec("V4-Q022", "600276", "恒瑞医药", "对外许可交易收入是否具备持续性"),
    QuerySpec("V4-Q023", "600276", "恒瑞医药", "创新药纳入医保后的降价与放量能否改善收入结构"),
    QuerySpec("V4-Q024", "600276", "恒瑞医药", "研发投入强度能否被经营现金流稳定覆盖"),
    QuerySpec("V4-Q025", "603259", "药明康德", "海外客户需求与在手订单恢复能否支撑收入增长"),
    QuerySpec("V4-Q026", "603259", "药明康德", "地缘政治与监管变化是否影响客户留存和产能利用"),
    QuerySpec("V4-Q027", "603259", "药明康德", "资产减值与产能调整是否会持续影响盈利质量"),
    QuerySpec("V4-Q028", "000538", "云南白药", "医药工业新品与临床管线能否贡献新的收入增长"),
    QuerySpec("V4-Q029", "000538", "云南白药", "核心产品销售恢复能否改善收入与毛利表现"),
    QuerySpec("V4-Q030", "000538", "云南白药", "关联交易与渠道调整是否会影响经营独立性"),
)


_FINANCIAL_TITLE = re.compile(r"年度报告|半年度报告|季度报告|业绩快报|业绩预告|盈利预告")
_GOVERNANCE_TITLE = re.compile(
    r"股东|董事会|监事会|质押|月报表|股权激励|股票期权|利润分配|章程|关联交易|关连交易"
)
_SPACE_RE = re.compile(r"\s+")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _v3_exclusions() -> tuple[set[str], set[str]]:
    rows = _read_csv(V3_GOLD)
    return (
        {row["查询ID"].strip() for row in rows},
        {row["候选原文链接"].strip() for row in rows if row["候选原文链接"].strip()},
    )


def _load_documents(security_id: str, excluded_urls: set[str]) -> list[CandidateDocument]:
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
            documents = [
                CandidateDocument(
                    document_id=row["document_id"],
                    security_id=row["security_id"],
                    title=_SPACE_RE.sub(" ", row["title"]).strip(),
                    published_at=row["published_at"],
                    source_url=str(row["source_url"] or "").strip(),
                )
                for row in raw
                if str(row["source_url"] or "").startswith(("http://", "https://"))
                and str(row["source_url"] or "").strip() not in excluded_urls
            ]
    finally:
        engine.dispose()
    return documents


def _retriever(documents: list[CandidateDocument]) -> DiversityReranker:
    base = CandidateUnionRetriever(
        primary=BM25Retriever(),
        supplemental=(ChineseVectorRetriever(), KeywordRetriever()),
    )
    prior = AnnouncementTypePriorRetriever(
        base,
        governance_penalty=0.35,
        candidate_multiplier=3,
    )
    retriever = DiversityReranker(prior, relevance_weight=0.82, candidate_multiplier=3)
    retriever.add(
        [
            RetrievalDocument(
                document_id=document.document_id,
                security_id=document.security_id,
                locator=document.document_id,
                content=document.title,
                published_at=document.published_at,
                visibility_label="公开",
                source=document.title,
            )
            for document in documents
        ]
    )
    return retriever


def _ordered_candidates(
    spec: QuerySpec,
    documents: list[CandidateDocument],
    retriever: DiversityReranker,
) -> list[CandidateDocument]:
    by_id = {document.document_id: document for document in documents}
    result = retriever.search(
        RetrievalQuery(
            text=spec.hypothesis,
            security_id=spec.security_id,
            as_of=CUTOFF,
            allowed_visibility=frozenset({"公开"}),
            top_k=48,
        )
    )
    ranked = [by_id[item.document_id] for item in result.items if item.document_id in by_id]
    recent = sorted(documents, key=lambda item: (-item.published_at.timestamp(), item.document_id))

    ordered: list[CandidateDocument] = []
    seen: set[str] = set()

    def add(items: list[CandidateDocument], limit: int | None = None) -> None:
        added = 0
        for item in items:
            if item.document_id in seen:
                continue
            ordered.append(item)
            seen.add(item.document_id)
            added += 1
            if limit is not None and added >= limit:
                break

    add(ranked, 5)
    add([item for item in ranked + recent if _FINANCIAL_TITLE.search(item.title)], 2)
    add([item for item in ranked + recent if _GOVERNANCE_TITLE.search(item.title)], 2)
    add(ranked)
    add(recent)
    return ordered


def _cache_path(cache_dir: Path, candidate: CandidateDocument) -> Path:
    suffix = hashlib.sha256(candidate.source_url.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"{candidate.document_id}-{suffix}.pdf"


def _download(client: httpx.Client, candidate: CandidateDocument, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, candidate)
    if path.is_file() and path.stat().st_size > 100:
        return path
    response = client.get(candidate.source_url)
    response.raise_for_status()
    if not response.content.startswith(b"%PDF"):
        raise ValueError("source is not a PDF")
    path.write_bytes(response.content)
    return path


def _extract_pages(path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(path))
    count = len(reader.pages)
    indices = list(range(min(count, 50)))
    if count > 70:
        indices.extend(range(count - 15, count))
    pages: list[tuple[int, str]] = []
    for index in dict.fromkeys(indices):
        try:
            content = reader.pages[index].extract_text() or ""
        except Exception:
            continue
        cleaned = _SPACE_RE.sub(" ", content).strip()
        if cleaned:
            pages.append((index + 1, cleaned))
    if not pages:
        raise ValueError("PDF contains no extractable text")
    return pages


def _best_excerpt(pages: list[tuple[int, str]], hypothesis: str, title: str) -> tuple[str, str]:
    query_terms = set(tokenize_zh_terms(f"{hypothesis} {title}"))
    best: tuple[float, int, str] | None = None
    for page_number, page_text in pages:
        chunks = [
            page_text[start : start + 700]
            for start in range(0, max(len(page_text), 1), 520)
            if len(page_text[start : start + 700].strip()) >= 50
        ]
        for chunk in chunks:
            terms = set(tokenize_zh_terms(chunk))
            overlap = query_terms & terms
            score: float = float(sum(2 if len(term) >= 3 else 1 for term in overlap))
            # Prefer substantive passages over recurring legal boilerplate when lexical
            # relevance is tied.  This is deterministic retrieval, not a relevance label.
            score += min(len(chunk), 500) / 1000
            if "不存在任何虚假记载" in chunk:
                score -= 0.5
            candidate = (score, -page_number, chunk)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        raise ValueError("no usable evidence excerpt")
    page_number = -best[1]
    excerpt = best[2].strip()
    if len(excerpt) > 650:
        excerpt = excerpt[:647].rstrip() + "…"
    return f"第{page_number}页", excerpt


def prepare_pool(output_path: Path, cache_dir: Path) -> dict[str, Any]:
    v3_query_ids, v3_urls = _v3_exclusions()
    reused_query_ids = sorted({spec.query_id for spec in QUERY_SPECS} & v3_query_ids)
    if reused_query_ids:
        raise ValueError(f"v4 查询ID复用了 v3：{reused_query_ids}")
    if len({spec.query_id for spec in QUERY_SPECS}) != 30:
        raise ValueError("v4 查询必须恰好为 30 个唯一查询")

    documents_by_security = {
        security_id: _load_documents(security_id, v3_urls)
        for security_id in sorted({spec.security_id for spec in QUERY_SPECS})
    }
    retrievers = {
        security_id: _retriever(documents)
        for security_id, documents in documents_by_security.items()
    }
    page_cache: dict[str, list[tuple[int, str]]] = {}
    rows: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    client = httpx.Client(
        follow_redirects=True,
        timeout=45,
        headers={"User-Agent": "Mozilla/5.0 AI-Investment-Copilot-v4-evaluation"},
    )
    try:
        for spec in QUERY_SPECS:
            candidates = _ordered_candidates(
                spec,
                documents_by_security[spec.security_id],
                retrievers[spec.security_id],
            )
            accepted = 0
            for candidate in candidates:
                if accepted >= 8:
                    break
                try:
                    if candidate.document_id not in page_cache:
                        pdf_path = _download(client, candidate, cache_dir)
                        page_cache[candidate.document_id] = _extract_pages(pdf_path)
                    locator, excerpt = _best_excerpt(
                        page_cache[candidate.document_id], spec.hypothesis, candidate.title
                    )
                except Exception as exc:  # continue to the next frozen-source candidate
                    failures.append(
                        {
                            "query_id": spec.query_id,
                            "document_id": candidate.document_id,
                            "reason": str(exc)[:240],
                        }
                    )
                    continue
                accepted += 1
                relation_id = f"V4-R-{spec.query_id.removeprefix('V4-')}-C{accepted:02d}"
                event_id = f"V4-E-{spec.query_id.removeprefix('V4-')}-C{accepted:02d}"
                rows.append(
                    {
                        "关系样本ID": relation_id,
                        "事件样本ID": event_id,
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
            if accepted < 8:
                raise RuntimeError(f"{spec.query_id} 仅取得 {accepted} 个可核验候选")
    finally:
        client.close()

    counts = _validate_base(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BASE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    manifest: dict[str, Any] = {
        "schema_version": POOL_VERSION,
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "cutoff": CUTOFF.isoformat(),
        "queries": len(counts),
        "rows": len(rows),
        "candidates_per_query": sorted(set(counts.values())),
        "companies": len({spec.security_id for spec in QUERY_SPECS}),
        "source_documents": len({row["候选文档ID"] for row in rows}),
        "source": "listed-company public disclosures",
        "v3_query_reuse": 0,
        "v3_candidate_url_reuse": 0,
        "label_columns_written": False,
        "download_or_parse_failures_skipped": failures,
    }
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    result = prepare_pool(args.output, args.cache_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
