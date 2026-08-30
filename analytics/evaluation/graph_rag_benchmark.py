"""Graph RAG final-gold system benchmark.

The benchmark evaluates the production ``GraphRetriever`` against the frozen
Graph-RAG relevance task.  Graph edges are built only from the query text,
candidate source text and a versioned deterministic concept vocabulary.  Gold
relevance labels are used only after ranking, never to construct the graph.

Besides retrieval quality, every query receives three adversarial canaries:

* an exact-match document owned by another security;
* an exact-match restricted document;
* an exact-match document published after the query cutoff.

Any canary in a result, graph path or citation is a hard rollout failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any

from app.ai.graph_rag import (
    GRAPH_RAG_VERSION,
    EvidenceFusionGraphRetriever,
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeKind,
    GraphRetriever,
    InvestmentKnowledgeGraph,
    RankStableGraphAssistRetriever,
)
from app.ai.retrieval import (
    GOVERNANCE_TERMS,
    AnnouncementTypePriorRetriever,
    BM25Retriever,
    CandidateUnionRetriever,
    ChineseVectorRetriever,
    DiversityReranker,
    KeywordRetriever,
    RetrievalDocument,
    RetrievalQuery,
    Retriever,
    tokenize_zh_terms,
)
from app.core.config import PROJECT_ROOT

BENCHMARK_VERSION = "graph-rag-evidence-fusion-closed-pool-v4"
VOCABULARY_VERSION = "investment-concepts-v2-controlled"
DEFAULT_GOLD = (
    PROJECT_ROOT
    / "analytics"
    / "datasets"
    / "final-gold-v3-20260826"
    / "final_graph_relevance_gold_v3.csv"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "analytics"
    / "experiments"
    / "20260826-graph-rag-final-gold-v3"
    / "graph_rag_benchmark.json"
)
DEFAULT_QUALITY_REPORT = (
    PROJECT_ROOT / "analytics" / "datasets" / "final-gold-v3-20260826" / "quality_report.json"
)

# Frozen before the first final-gold run.  These are release gates, not targets
# adjusted after observing the evaluation output.
QUALITY_THRESHOLDS: dict[str, float | int] = {
    "minimum_positive_queries": 20,
    "recall_at_5": 0.80,
    "mrr": 0.65,
    "ndcg_at_5": 0.75,
    "top1_correctness": 0.70,
    "path_provenance_rate": 0.95,
    "candidate_pool_compliance_rate": 1.0,
    "maximum_recall_regression_vs_text": 0.01,
    "maximum_unjudged_results": 0,
    "maximum_permission_leaks": 0,
    "maximum_security_leaks": 0,
    "maximum_future_leaks": 0,
    "maximum_canary_content_leaks": 0,
}

# Concepts represent the semantic layer used by the benchmark projection.  A
# term may appear in several concepts because investment hypotheses are often
# multi-causal; no label or adjudication field is referenced here.
INVESTMENT_CONCEPTS_V1: dict[str, tuple[str, ...]] = {
    "需求与出货": ("需求", "销量", "产量", "产销", "出货", "交付", "订单"),
    "盈利质量": ("毛利", "毛利率", "利润", "净利润", "盈利", "亏损", "成本", "价格", "降价"),
    "收入增长": ("收入", "营收", "销售额", "营业收入"),
    "现金流": ("现金流", "经营活动", "回款", "应收", "现金净额"),
    "创新研发": ("研发", "创新药", "临床", "适应症", "注册证", "获批", "专利", "产品迭代"),
    "产能与利用率": ("产能", "扩产", "投产", "工厂", "基地", "利用率", "稼动率", "在建工程"),
    "资本开支与减值": ("资本开支", "投资", "减值", "固定资产", "在建工程", "设备"),
    "整合与协同": (
        "整合",
        "协同",
        "收购",
        "注资",
        "合并",
        "平台",
        "品牌",
        "购销",
        "关联交易",
        "關連交易",
    ),
    "海外经营": ("海外", "出口", "境外", "国际", "全球"),
    "市场份额": ("份额", "市占率", "市场占有率", "竞争力"),
    "政策与监管": ("政策", "监管", "集采", "制裁", "出口管制", "关税"),
    "供应链与库存": ("供应链", "零部件", "采购", "库存", "渠道"),
    "治理与证券事项": (
        "质押",
        "股东",
        "持股",
        "股份",
        "分红",
        "利润分配",
        "章程",
        "董事会",
        "监事会",
        "月报表",
        "员工持股",
        "认股权",
    ),
}

# v2 只加入在公告与指标字典中可解释的受控同义词，不读取 v3/v4 的相关性标签。
# 保留 v1 常量用于单项消融，避免把词表变化与排序器变化混在一起。
INVESTMENT_CONCEPTS_V2: dict[str, tuple[str, ...]] = {
    **INVESTMENT_CONCEPTS_V1,
    "需求与出货": (
        *INVESTMENT_CONCEPTS_V1["需求与出货"],
        "合同负债",
        "在手订单",
        "订单量",
        "交付量",
        "装机量",
        "批签发",
    ),
    "盈利质量": (
        *INVESTMENT_CONCEPTS_V1["盈利质量"],
        "毛利率",
        "净利率",
        "产品结构",
        "规模效应",
        "折旧",
        "价格战",
    ),
    "收入增长": (*INVESTMENT_CONCEPTS_V1["收入增长"], "主营业务收入", "销售收入"),
    "现金流": (*INVESTMENT_CONCEPTS_V1["现金流"], "自由现金流", "经营现金流", "现金及等价物"),
    "创新研发": (
        *INVESTMENT_CONCEPTS_V1["创新研发"],
        "研发投入",
        "研发费用",
        "管线",
        "里程碑",
        "商业化",
        "新车型",
        "新产品",
    ),
    "产能与利用率": (
        *INVESTMENT_CONCEPTS_V1["产能与利用率"],
        "产能利用率",
        "产量利用率",
        "满产",
        "达产",
        "晶圆厂",
    ),
    "资本开支与减值": (
        *INVESTMENT_CONCEPTS_V1["资本开支与减值"],
        "资本性支出",
        "资产减值",
        "存货跌价",
        "商誉减值",
    ),
    "整合与协同": (
        *INVESTMENT_CONCEPTS_V1["整合与协同"],
        "平台整合",
        "品牌整合",
        "垂直一体化",
    ),
    "海外经营": (*INVESTMENT_CONCEPTS_V1["海外经营"], "出海", "海外基地", "海外工厂", "国际化"),
    "市场份额": (*INVESTMENT_CONCEPTS_V1["市场份额"], "国产替代", "国产化", "渗透率"),
    "政策与监管": (*INVESTMENT_CONCEPTS_V1["政策与监管"], "地缘政治", "实体清单", "贸易限制"),
    "供应链与库存": (
        *INVESTMENT_CONCEPTS_V1["供应链与库存"],
        "存货",
        "库存周期",
        "去库存",
        "备货",
    ),
}


@dataclass(frozen=True)
class BenchmarkVariant:
    """单项消融开关；Graph 权重和发布阈值不属于变量。"""

    name: str
    enhanced_concepts: bool = False
    announcement_prior: bool = False
    bm25: bool = False
    chinese_vector: bool = False
    diversity: bool = False
    rank_stable_assist: bool = False
    evidence_fusion: bool = False
    announcement_penalty: float = 0.35


BASELINE_VARIANT = BenchmarkVariant("v1_baseline")
LEGACY_RELEASE_CANDIDATE_VARIANT = BenchmarkVariant(
    "p0_assisted_release_candidate",
    enhanced_concepts=True,
    announcement_prior=True,
    bm25=True,
    chinese_vector=True,
    diversity=True,
    rank_stable_assist=True,
)
RELEASE_CANDIDATE_VARIANT = BenchmarkVariant(
    "p0_evidence_fusion_release_candidate",
    bm25=True,
    evidence_fusion=True,
)
ABLATION_VARIANTS = (
    BASELINE_VARIANT,
    BenchmarkVariant("controlled_concepts_only", enhanced_concepts=True),
    BenchmarkVariant("announcement_prior_only", announcement_prior=True),
    BenchmarkVariant("bm25_only", bm25=True),
    BenchmarkVariant("chinese_vector_only", chinese_vector=True),
    BenchmarkVariant("diversity_only", diversity=True),
    LEGACY_RELEASE_CANDIDATE_VARIANT,
    RELEASE_CANDIDATE_VARIANT,
)

GRADE = {"0-无关": 0, "1-弱相关": 1, "2-间接相关": 2, "3-直接相关": 3}
TOP_KS = (1, 3, 5, 10)


@dataclass(frozen=True)
class GoldRow:
    relation_id: str
    event_id: str
    candidate_id: str
    query_id: str
    company: str
    security_id: str
    cutoff: datetime
    hypothesis: str
    title: str
    excerpt: str
    published_at: datetime
    grade: int

    @property
    def document_id(self) -> str:
        return f"BENCH-{self.candidate_id}"

    @property
    def locator(self) -> str:
        return f"{self.document_id}#paragraph-1"


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"检索截止时间缺少时区：{value}")
    return parsed


def load_gold(path: Path) -> list[GoldRow]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {
        "关系样本ID",
        "事件样本ID",
        "查询ID",
        "公司",
        "证券代码",
        "检索截止时间",
        "查询假设",
        "候选公告标题",
        "相关性等级",
        "关键证据原文",
    }
    if not rows or not required.issubset(rows[0]):
        missing = sorted(required - set(rows[0] if rows else ()))
        raise ValueError(f"Graph RAG 金标缺少字段：{missing}")
    result: list[GoldRow] = []
    for row in rows:
        label = row["相关性等级"]
        if label not in GRADE:
            raise ValueError(f"未知相关性等级：{label}")
        result.append(
            GoldRow(
                relation_id=row["关系样本ID"],
                event_id=row["事件样本ID"],
                candidate_id=(row.get("候选文档ID") or row["事件样本ID"]).strip(),
                query_id=row["查询ID"],
                company=row["公司"],
                security_id=row["证券代码"],
                cutoff=_parse_time(row["检索截止时间"]),
                hypothesis=row["查询假设"],
                title=row["候选公告标题"],
                excerpt=row["关键证据原文"],
                published_at=(
                    _parse_time(row["候选发布日期"])
                    if row.get("候选发布日期")
                    else _parse_time(row["检索截止时间"])
                ),
                grade=GRADE[label],
            )
        )
    if len({row.relation_id for row in result}) != len(result):
        raise ValueError("关系样本ID必须唯一")
    return result


def _concept_matches(
    text: str, concepts: dict[str, tuple[str, ...]] = INVESTMENT_CONCEPTS_V2
) -> dict[str, int]:
    normalized = text.lower()
    return {
        concept: sum(normalized.count(term.lower()) for term in terms)
        for concept, terms in concepts.items()
        if any(term.lower() in normalized for term in terms)
    }


def _edge_weight(matches: int) -> float:
    return min(1.0, 0.72 + min(matches, 7) * 0.04)


def _add_fact_projection(
    graph: InvestmentKnowledgeGraph,
    document: RetrievalDocument,
    *,
    fact_id: str,
    concepts: dict[str, int],
) -> None:
    fact_node_id = f"benchmark-fact:{fact_id}"
    graph.add_node(
        GraphNode(
            fact_node_id,
            GraphNodeKind.FACT,
            document.source,
            content=document.content,
            security_id=document.security_id,
            published_at=document.published_at,
            visibility_label=document.visibility_label,
            locator=document.locator,
            metadata={"document_id": document.document_id},
        )
    )
    graph.add_edge(
        GraphEdge(
            GraphRetriever.segment_node_id(document.locator),
            fact_node_id,
            GraphEdgeKind.STATES_FACT,
            provenance_locator=document.locator,
        )
    )
    for concept, matches in concepts.items():
        concept_node_id = f"benchmark-concept:{concept}"
        graph.add_node(GraphNode(concept_node_id, GraphNodeKind.BUSINESS_VARIABLE, concept))
        graph.add_edge(
            GraphEdge(
                fact_node_id,
                concept_node_id,
                GraphEdgeKind.AFFECTS,
                weight=_edge_weight(matches),
                provenance_locator=document.locator,
            )
        )


def _canary_documents(
    grouped: dict[str, list[GoldRow]],
) -> tuple[list[RetrievalDocument], dict[str, str]]:
    documents: list[RetrievalDocument] = []
    tokens: dict[str, str] = {}
    for query_id, rows in grouped.items():
        sample = rows[0]
        as_of = max(row.cutoff for row in rows)
        specs = (
            ("permission", sample.security_id, as_of, "机密"),
            ("security", f"OTHER-{sample.security_id}", as_of, "公开"),
            ("future", sample.security_id, as_of + timedelta(days=1), "公开"),
        )
        for kind, security_id, published_at, visibility in specs:
            token = f"CANARY-{kind.upper()}-{query_id}"
            locator = f"BENCH-{token}#paragraph-1"
            tokens[token] = kind
            documents.append(
                RetrievalDocument(
                    document_id=f"BENCH-{token}",
                    security_id=security_id,
                    locator=locator,
                    content=f"{sample.hypothesis} {sample.hypothesis} {token}",
                    published_at=published_at,
                    visibility_label=visibility,
                    source=token,
                    metadata={"canary_type": kind, "canary_token": token},
                )
            )
    return documents, tokens


def _build_retrievers(
    rows: list[GoldRow],
    variant: BenchmarkVariant,
) -> tuple[Retriever, Retriever, dict[str, list[GoldRow]], dict[str, str]]:
    grouped: dict[str, list[GoldRow]] = defaultdict(list)
    unique_candidates: dict[str, GoldRow] = {}
    for row in rows:
        grouped[row.query_id].append(row)
        unique_candidates.setdefault(row.candidate_id, row)

    documents = [
        RetrievalDocument(
            document_id=row.document_id,
            security_id=row.security_id,
            locator=row.locator,
            content=f"{row.title}\n{row.excerpt}",
            published_at=row.published_at,
            visibility_label="公开",
            source=row.title,
            metadata={
                "candidate_document_id": row.candidate_id,
                "event_sample_id": row.event_id,
            },
        )
        for row in unique_candidates.values()
    ]
    canaries, canary_tokens = _canary_documents(grouped)
    all_documents = [*documents, *canaries]

    graph = InvestmentKnowledgeGraph()

    def candidate_retriever() -> Retriever:
        supplemental: list[Retriever] = []
        if variant.bm25:
            supplemental.append(BM25Retriever())
        if variant.chinese_vector:
            supplemental.append(ChineseVectorRetriever())
        return (
            CandidateUnionRetriever(primary=KeywordRetriever(), supplemental=tuple(supplemental))
            if supplemental
            else KeywordRetriever()
        )

    def apply_rerankers(retriever: Retriever) -> Retriever:
        if variant.announcement_prior:
            retriever = AnnouncementTypePriorRetriever(
                retriever, governance_penalty=variant.announcement_penalty
            )
        if variant.diversity:
            retriever = DiversityReranker(retriever)
        return retriever

    text_retriever = apply_rerankers(candidate_retriever())
    graph_core = GraphRetriever(
        text_retriever=(KeywordRetriever() if variant.evidence_fusion else candidate_retriever()),
        graph=graph,
        text_weight=0.35,
        graph_weight=0.65,
        max_hops=4,
        snapshot_metadata={
            "snapshot_id": "benchmark:final-gold-v3-20260826",
            "schema_version": "benchmark-projection-v1",
            "builder_version": BENCHMARK_VERSION,
            "vocabulary_version": (
                VOCABULARY_VERSION if variant.enhanced_concepts else "investment-concepts-v1"
            ),
        },
    )
    graph_retriever = apply_rerankers(graph_core)
    evaluated_retriever: Retriever = (
        EvidenceFusionGraphRetriever(
            text_retriever=KeywordRetriever(),
            bm25_retriever=BM25Retriever(),
            graph_retriever=graph_retriever,
        )
        if variant.evidence_fusion
        else RankStableGraphAssistRetriever(
            text_retriever=text_retriever,
            graph_retriever=graph_retriever,
        )
        if variant.rank_stable_assist
        else graph_retriever
    )
    if variant.rank_stable_assist or variant.evidence_fusion:
        text_retriever.add(all_documents)
        evaluated_retriever.add(all_documents)
    else:
        text_retriever.add(all_documents)
        evaluated_retriever.add(all_documents)

    concepts = INVESTMENT_CONCEPTS_V2 if variant.enhanced_concepts else INVESTMENT_CONCEPTS_V1

    for document in all_documents:
        event_id = str(document.metadata.get("candidate_document_id") or document.document_id)
        _add_fact_projection(
            graph,
            document,
            fact_id=event_id,
            concepts=_concept_matches(document.content, concepts),
        )
    for query_id, query_rows in grouped.items():
        sample = query_rows[0]
        hypothesis_node_id = f"benchmark-hypothesis:{query_id}"
        graph.add_node(
            GraphNode(
                hypothesis_node_id,
                GraphNodeKind.HYPOTHESIS,
                sample.hypothesis,
                content=sample.hypothesis,
                security_id=sample.security_id,
            )
        )
        for concept, matches in _concept_matches(sample.hypothesis, concepts).items():
            concept_node_id = f"benchmark-concept:{concept}"
            graph.add_node(GraphNode(concept_node_id, GraphNodeKind.BUSINESS_VARIABLE, concept))
            graph.add_edge(
                GraphEdge(
                    hypothesis_node_id,
                    concept_node_id,
                    GraphEdgeKind.DEPENDS_ON,
                    weight=_edge_weight(matches),
                )
            )
    return text_retriever, evaluated_retriever, dict(grouped), canary_tokens


def _event_ids(items: list[Any]) -> list[str]:
    return [
        str(item.metadata.get("candidate_document_id") or item.metadata.get("canary_token") or "")
        for item in items
    ]


def _dcg(grades: list[int], k: int) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades[:k]))


def _rank_metrics(
    rankings: dict[str, list[str]],
    grouped: dict[str, list[GoldRow]],
) -> dict[str, Any]:
    positive_queries = [
        query_id for query_id, rows in grouped.items() if any(row.grade >= 2 for row in rows)
    ]
    recall_by_k: dict[int, list[float]] = {k: [] for k in TOP_KS}
    hit_by_k: dict[int, list[float]] = {k: [] for k in TOP_KS}
    ndcg_by_k: dict[int, list[float]] = {k: [] for k in TOP_KS}
    reciprocals: list[float] = []
    top1: list[float] = []
    unjudged = 0
    for query_id, rows in grouped.items():
        grades = {row.candidate_id: row.grade for row in rows}
        ranking = rankings[query_id]
        unjudged += sum(item not in grades and not item.startswith("CANARY-") for item in ranking)
        top1.append(float(bool(ranking) and grades.get(ranking[0], 0) >= 2))
        if query_id not in positive_queries:
            continue
        positives = {candidate_id for candidate_id, grade in grades.items() if grade >= 2}
        first_rank = next(
            (index for index, candidate_id in enumerate(ranking, 1) if candidate_id in positives),
            None,
        )
        reciprocals.append(1 / first_rank if first_rank else 0.0)
        ideal = sorted(grades.values(), reverse=True)
        ranked_grades = [grades.get(candidate_id, 0) for candidate_id in ranking]
        for k in TOP_KS:
            found = positives & set(ranking[:k])
            recall_by_k[k].append(len(found) / len(positives))
            hit_by_k[k].append(float(bool(found)))
            ideal_dcg = _dcg(ideal, k)
            ndcg_by_k[k].append(_dcg(ranked_grades, k) / ideal_dcg if ideal_dcg else 0.0)
    return {
        "evaluated_queries": len(grouped),
        "positive_queries": len(positive_queries),
        "recall_at_k": {str(k): round(fmean(values), 4) for k, values in recall_by_k.items()},
        "hit_rate_at_k": {str(k): round(fmean(values), 4) for k, values in hit_by_k.items()},
        "ndcg_at_k": {str(k): round(fmean(values), 4) for k, values in ndcg_by_k.items()},
        "mrr": round(fmean(reciprocals), 4),
        "top1_correctness": round(fmean(top1), 4),
        "unjudged_result_count": unjudged,
    }


def _path_provenance_rate(
    results: dict[str, list[Any]], grouped: dict[str, list[GoldRow]], *, k: int = 5
) -> tuple[float, int, int]:
    valid = 0
    relevant = 0
    for query_id, items in results.items():
        grades = {row.candidate_id: row.grade for row in grouped[query_id]}
        for item in items[:k]:
            candidate_id = str(item.metadata.get("candidate_document_id") or "")
            if grades.get(candidate_id, 0) < 2:
                continue
            relevant += 1
            paths = item.metadata.get("graph_paths") or []
            if any(item.locator in (path.get("provenance_locators") or []) for path in paths):
                valid += 1
    return (round(valid / relevant, 4) if relevant else 0.0, valid, relevant)


def _safety_metrics(results: dict[str, list[Any]], canary_tokens: dict[str, str]) -> dict[str, int]:
    counts = {
        "permission_leakage_count": 0,
        "security_leakage_count": 0,
        "future_leakage_count": 0,
        "canary_content_leakage_count": 0,
    }
    for items in results.values():
        for item in items:
            kind = item.metadata.get("canary_type")
            if kind:
                counts[f"{kind}_leakage_count"] += 1
            serialized = json.dumps(
                {"content": item.content, "metadata": item.metadata},
                ensure_ascii=False,
                default=str,
            )
            if any(token in serialized for token in canary_tokens):
                counts["canary_content_leakage_count"] += 1
    return counts


def _gate(
    code: str, current: float | int | bool, target: float | int | bool, passed: bool
) -> dict[str, Any]:
    return {"code": code, "current": current, "target": target, "passed": passed}


def _is_governance(text: str) -> bool:
    normalized = text.lower()
    return any(term.lower() in normalized for term in GOVERNANCE_TERMS)


def _same_disclosure_theme(left: str, right: str) -> bool:
    def terms(value: str) -> set[str]:
        normalized = re.sub(r"20\d{2}|\d{1,2}月|第[一二三四1234]季度|年度|半年度", "", value)
        return set(tokenize_zh_terms(normalized))

    left_terms, right_terms = terms(left), terms(right)
    if not left_terms or not right_terms:
        return False
    return len(left_terms & right_terms) / len(left_terms | right_terms) >= 0.72


def _error_taxonomy(per_query: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[str]] = {
        "governance_hard_negative": [],
        "duplicate_disclosures": [],
        "too_many_positive_candidates": [],
        "graph_cannot_change_top1": [],
    }
    failed: list[str] = []
    for item in per_query:
        top1_failed = (item["graph_top1_grade"] or 0) < 2
        recall = item["graph_recall_at_5"]
        if top1_failed or (recall is not None and recall < 1.0):
            failed.append(item["query_id"])
        top_title = item.get("graph_top1_title") or ""
        if top1_failed and _is_governance(top_title) and not _is_governance(item["hypothesis"]):
            groups["governance_hard_negative"].append(item["query_id"])
        titles = [entry["title"] for entry in item["graph_top5"]]
        if any(
            _same_disclosure_theme(left, right)
            for index, left in enumerate(titles)
            for right in titles[index + 1 :]
        ):
            groups["duplicate_disclosures"].append(item["query_id"])
        if item["positive_candidates"] > 5:
            groups["too_many_positive_candidates"].append(item["query_id"])
        if top1_failed and item["graph_ranking"][:1] == item["text_ranking"][:1]:
            groups["graph_cannot_change_top1"].append(item["query_id"])
    definitions = {
        "governance_hard_negative": "经营类查询的 Graph Top-1 是治理类公告且相关性低于 2",
        "duplicate_disclosures": "Graph Top-5 存在去日期后标题词元 Jaccard≥0.72 的同主题公告",
        "too_many_positive_candidates": "单查询正例超过 5，Recall@5 的理论上限低于 1",
        "graph_cannot_change_top1": "错误 Top-1 与文本基线相同，图路径未纠正首位",
    }
    return {
        "failed_queries": len(set(failed)),
        "groups": {
            code: {
                "definition": definitions[code],
                "count": len(query_ids),
                "query_ids": query_ids,
            }
            for code, query_ids in groups.items()
        },
    }


def _per_query_report(
    grouped: dict[str, list[GoldRow]],
    text_rankings: dict[str, list[str]],
    graph_rankings: dict[str, list[str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for query_id, query_rows in sorted(grouped.items()):
        grades = {row.candidate_id: row.grade for row in query_rows}
        candidate_rows = {row.candidate_id: row for row in query_rows}
        relevant = {candidate_id for candidate_id, grade in grades.items() if grade >= 2}
        graph_top = graph_rankings[query_id][0] if graph_rankings[query_id] else None
        rows.append(
            {
                "query_id": query_id,
                "company": query_rows[0].company,
                "security_id": query_rows[0].security_id,
                "hypothesis": query_rows[0].hypothesis,
                "positive_candidates": len(relevant),
                "text_recall_at_5": (
                    round(len(relevant & set(text_rankings[query_id][:5])) / len(relevant), 4)
                    if relevant
                    else None
                ),
                "graph_recall_at_5": (
                    round(len(relevant & set(graph_rankings[query_id][:5])) / len(relevant), 4)
                    if relevant
                    else None
                ),
                "graph_top1_grade": grades.get(graph_top, 0) if graph_top else None,
                "graph_top1_title": (
                    candidate_rows[graph_top].title if graph_top in candidate_rows else None
                ),
                "text_ranking": text_rankings[query_id],
                "graph_ranking": graph_rankings[query_id],
                "graph_top5": [
                    {
                        "event_id": event_id,
                        "title": candidate_rows[event_id].title,
                        "grade": grades[event_id],
                    }
                    for event_id in graph_rankings[query_id][:5]
                    if event_id in candidate_rows
                ],
                "gold_grades": grades,
            }
        )
    return rows


def run_benchmark(
    gold_path: Path,
    *,
    variant: BenchmarkVariant = RELEASE_CANDIDATE_VARIANT,
    evaluation_role: str = "revealed_regression",
) -> dict[str, Any]:
    if evaluation_role not in {"revealed_regression", "one_time_blind"}:
        raise ValueError(f"未知评测角色：{evaluation_role}")
    rows = load_gold(gold_path)
    lexical, graph, grouped, canary_tokens = _build_retrievers(rows, variant)
    text_results: dict[str, list[Any]] = {}
    graph_results: dict[str, list[Any]] = {}
    graph_retrieval_version = GRAPH_RAG_VERSION
    for query_id, query_rows in sorted(grouped.items()):
        sample = query_rows[0]
        allowed_document_ids = {
            *(row.document_id for row in query_rows),
            *(f"BENCH-CANARY-{kind}-{query_id}" for kind in ("PERMISSION", "SECURITY", "FUTURE")),
        }
        query = RetrievalQuery(
            text=sample.hypothesis,
            security_id=sample.security_id,
            as_of=max(row.cutoff for row in query_rows),
            allowed_visibility=frozenset({"公开"}),
            top_k=10,
            allowed_document_ids=frozenset(allowed_document_ids),
            seed_node_ids=frozenset({f"benchmark-hypothesis:{query_id}"}),
        )
        text_results[query_id] = lexical.search(query).items
        graph_result = graph.search(query)
        graph_results[query_id] = graph_result.items
        graph_retrieval_version = graph_result.retrieval_version

    text_rankings = {query_id: _event_ids(items) for query_id, items in text_results.items()}
    graph_rankings = {query_id: _event_ids(items) for query_id, items in graph_results.items()}
    text_metrics = _rank_metrics(text_rankings, grouped)
    graph_metrics = _rank_metrics(graph_rankings, grouped)
    rank_stability_rate = round(
        fmean(
            float(
                [item for item in graph_rankings[query_id] if item in set(text_rankings[query_id])]
                == text_rankings[query_id]
            )
            for query_id in grouped
        ),
        4,
    )
    candidate_pool_compliance_rate = round(
        fmean(
            float(
                all(
                    candidate_id in {row.candidate_id for row in grouped[query_id]}
                    for candidate_id in graph_rankings[query_id]
                )
            )
            for query_id in grouped
        ),
        4,
    )
    path_rate, valid_paths, relevant_paths = _path_provenance_rate(graph_results, grouped)
    safety: dict[str, int | float] = {}
    safety.update(_safety_metrics(graph_results, canary_tokens))
    safety["adversarial_canary_count"] = len(canary_tokens)
    safety["path_provenance_valid"] = valid_paths
    safety["path_provenance_relevant_hits"] = relevant_paths
    safety["path_provenance_rate"] = path_rate

    gates = [
        _gate(
            "minimum_positive_queries",
            graph_metrics["positive_queries"],
            QUALITY_THRESHOLDS["minimum_positive_queries"],
            graph_metrics["positive_queries"] >= QUALITY_THRESHOLDS["minimum_positive_queries"],
        ),
        _gate(
            "recall_at_5",
            graph_metrics["recall_at_k"]["5"],
            QUALITY_THRESHOLDS["recall_at_5"],
            graph_metrics["recall_at_k"]["5"] >= QUALITY_THRESHOLDS["recall_at_5"],
        ),
        _gate(
            "mrr",
            graph_metrics["mrr"],
            QUALITY_THRESHOLDS["mrr"],
            graph_metrics["mrr"] >= QUALITY_THRESHOLDS["mrr"],
        ),
        _gate(
            "ndcg_at_5",
            graph_metrics["ndcg_at_k"]["5"],
            QUALITY_THRESHOLDS["ndcg_at_5"],
            graph_metrics["ndcg_at_k"]["5"] >= QUALITY_THRESHOLDS["ndcg_at_5"],
        ),
        _gate(
            "top1_correctness",
            graph_metrics["top1_correctness"],
            QUALITY_THRESHOLDS["top1_correctness"],
            graph_metrics["top1_correctness"] >= QUALITY_THRESHOLDS["top1_correctness"],
        ),
        _gate(
            "path_provenance_rate",
            path_rate,
            QUALITY_THRESHOLDS["path_provenance_rate"],
            path_rate >= QUALITY_THRESHOLDS["path_provenance_rate"],
        ),
        _gate(
            "candidate_pool_compliance_rate",
            candidate_pool_compliance_rate,
            QUALITY_THRESHOLDS["candidate_pool_compliance_rate"],
            candidate_pool_compliance_rate >= QUALITY_THRESHOLDS["candidate_pool_compliance_rate"],
        ),
        _gate(
            "closed_pool_no_unjudged",
            graph_metrics["unjudged_result_count"],
            QUALITY_THRESHOLDS["maximum_unjudged_results"],
            graph_metrics["unjudged_result_count"] <= QUALITY_THRESHOLDS["maximum_unjudged_results"]
            and text_metrics["unjudged_result_count"]
            <= QUALITY_THRESHOLDS["maximum_unjudged_results"],
        ),
        _gate(
            "graph_recall_regression_within_tolerance",
            graph_metrics["recall_at_k"]["5"],
            round(
                text_metrics["recall_at_k"]["5"]
                - QUALITY_THRESHOLDS["maximum_recall_regression_vs_text"],
                4,
            ),
            graph_metrics["recall_at_k"]["5"]
            >= text_metrics["recall_at_k"]["5"]
            - QUALITY_THRESHOLDS["maximum_recall_regression_vs_text"],
        ),
        _gate(
            "graph_mrr_not_worse_than_text",
            graph_metrics["mrr"],
            text_metrics["mrr"],
            graph_metrics["mrr"] >= text_metrics["mrr"],
        ),
        _gate(
            "permission_leakage",
            safety["permission_leakage_count"],
            QUALITY_THRESHOLDS["maximum_permission_leaks"],
            safety["permission_leakage_count"] == 0,
        ),
        _gate(
            "security_leakage",
            safety["security_leakage_count"],
            QUALITY_THRESHOLDS["maximum_security_leaks"],
            safety["security_leakage_count"] == 0,
        ),
        _gate(
            "future_leakage",
            safety["future_leakage_count"],
            QUALITY_THRESHOLDS["maximum_future_leaks"],
            safety["future_leakage_count"] == 0,
        ),
        _gate(
            "canary_content_leakage",
            safety["canary_content_leakage_count"],
            QUALITY_THRESHOLDS["maximum_canary_content_leaks"],
            safety["canary_content_leakage_count"] == 0,
        ),
    ]
    per_query = _per_query_report(grouped, text_rankings, graph_rankings)
    lowered_gold_path = str(gold_path).lower()
    gold_version = next(
        (
            f"graph-relevance-{version}-blind"
            for version in ("v6", "v5", "v4")
            if version in lowered_gold_path
        ),
        "final-gold-v3-20260826",
    )
    return {
        "schema_version": "graph-rag-benchmark-v3",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "gold_version": gold_version,
        "evaluation_role": evaluation_role,
        "gold_file": gold_path.name,
        "retrieval_version": graph_retrieval_version,
        "vocabulary_version": (
            VOCABULARY_VERSION if variant.enhanced_concepts else "investment-concepts-v1"
        ),
        "variant": {
            "name": variant.name,
            "enhanced_concepts": variant.enhanced_concepts,
            "announcement_prior": variant.announcement_prior,
            "bm25": variant.bm25,
            "chinese_vector": variant.chinese_vector,
            "diversity": variant.diversity,
            "rank_stable_assist": variant.rank_stable_assist,
            "evidence_fusion": variant.evidence_fusion,
            "announcement_penalty": variant.announcement_penalty,
            "graph_text_weight": 0.35,
            "graph_relation_weight": 0.65,
            "fusion_text_weight": 0.25 if variant.evidence_fusion else None,
            "fusion_bm25_weight": 0.5 if variant.evidence_fusion else None,
            "fusion_graph_weight": 1.0 if variant.evidence_fusion else None,
            "fusion_report_prior_weight": 1.0 if variant.evidence_fusion else None,
            "fusion_rrf_k": 1 if variant.evidence_fusion else None,
            "thresholds_changed": False,
        },
        "evaluation_protocol": {
            "relevant_grades": ["2-间接相关", "3-直接相关"],
            "recall_definition": "macro mean of relevant-set recall per positive query",
            "mrr_definition": "macro reciprocal rank of first relevant candidate per positive query",
            "zero_positive_queries_excluded_from_recall_and_mrr": True,
            "top1_correctness_includes_zero_positive_queries": True,
            "gold_labels_used_for_graph_construction": False,
            "candidate_pool_scope": "per_query_closed",
            "unjudged_policy": "hard_fail",
            "rank_policy": (
                "candidate_pool_constrained_graph_bm25_rrf_with_high_evidence_prior"
                if variant.evidence_fusion
                else "text_order_preserved_graph_paths_and_backfill"
            ),
            "thresholds_frozen_before_run": True,
            "v3_may_authorize_rollout": False,
        },
        "dataset": {
            "rows": len(rows),
            "queries": len(grouped),
            "positive_queries": sum(
                any(row.grade >= 2 for row in values) for values in grouped.values()
            ),
            "securities": len({row.security_id for row in rows}),
        },
        "text_baseline": text_metrics,
        "graph_rag": graph_metrics,
        "assist": {
            "rank_stability_rate": rank_stability_rate,
            "candidate_pool_compliance_rate": candidate_pool_compliance_rate,
        },
        "safety": safety,
        "thresholds": QUALITY_THRESHOLDS,
        "gates": gates,
        "rollout_ready": all(gate["passed"] for gate in gates),
        "error_taxonomy": _error_taxonomy(per_query),
        "per_query": per_query,
    }


def run_ablation_suite(gold_path: Path) -> dict[str, Any]:
    """在已揭盲回归集上逐项消融；不产生发布 READY 结论。"""

    reports = [run_benchmark(gold_path, variant=variant) for variant in ABLATION_VARIANTS]
    baseline = reports[0]["graph_rag"]
    rows: list[dict[str, Any]] = []
    for report in reports:
        graph = report["graph_rag"]
        rows.append(
            {
                "variant": report["variant"],
                "recall_at_5": graph["recall_at_k"]["5"],
                "mrr": graph["mrr"],
                "ndcg_at_5": graph["ndcg_at_k"]["5"],
                "top1_correctness": graph["top1_correctness"],
                "delta_vs_baseline": {
                    "recall_at_5": round(
                        graph["recall_at_k"]["5"] - baseline["recall_at_k"]["5"], 4
                    ),
                    "mrr": round(graph["mrr"] - baseline["mrr"], 4),
                    "ndcg_at_5": round(graph["ndcg_at_k"]["5"] - baseline["ndcg_at_k"]["5"], 4),
                    "top1_correctness": round(
                        graph["top1_correctness"] - baseline["top1_correctness"], 4
                    ),
                },
                "safety": report["safety"],
                "error_taxonomy": report["error_taxonomy"],
            }
        )
    return {
        "schema_version": "graph-rag-ablation-v1",
        "benchmark_version": BENCHMARK_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "gold_version": reports[0]["gold_version"],
        "evaluation_role": "revealed_regression",
        "weights_changed_between_variants": True,
        "thresholds_changed_between_variants": False,
        "variants": rows,
    }


def update_quality_report(path: Path, benchmark: dict[str, Any], report_path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    authoritative_blind = (
        benchmark.get("gold_version")
        in {"graph-relevance-v4-blind", "graph-relevance-v5-blind", "graph-relevance-v6-blind"}
        and benchmark.get("evaluation_role") == "one_time_blind"
    )
    ready = bool(benchmark["rollout_ready"] and authoritative_blind)
    payload["summary"]["graph_rag_rollout_ready"] = ready
    graph = benchmark["graph_rag"]
    safety = benchmark["safety"]
    prefix = (
        f"{benchmark['gold_version']} 一次性盲测"
        if authoritative_blind
        else f"{benchmark.get('gold_version', '未知版本')} 已揭盲回归（不可授权放量）"
    )
    message = (
        f"{prefix}：Recall@5={graph['recall_at_k']['5']:.4f}，"
        f"MRR={graph['mrr']:.4f}，Top-1={graph['top1_correctness']:.4f}；"
        f"权限/证券/未来泄漏={safety['permission_leakage_count']}/"
        f"{safety['security_leakage_count']}/{safety['future_leakage_count']}。"
    )
    for gate in payload["gates"]:
        if gate["code"] == "graph_rag_system_benchmark":
            gate.update(
                status="passed" if ready else "blocked",
                current=ready,
                target=True,
                message=message,
            )
            break
    else:
        payload["gates"].append(
            {
                "code": "graph_rag_system_benchmark",
                "label": "Graph RAG 系统离线基准",
                "status": "passed" if ready else "blocked",
                "current": ready,
                "target": True,
                "message": message,
            }
        )
    try:
        relative_report = report_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        relative_report = str(report_path)
    payload["system_benchmarks"] = {
        "graph_rag": {
            "benchmark_version": benchmark["benchmark_version"],
            "generated_at": benchmark["generated_at"],
            "report_path": relative_report,
            "rollout_ready": ready,
            "raw_gates_passed": bool(benchmark["rollout_ready"]),
            "authoritative_blind": authoritative_blind,
            "evaluated_queries": graph["evaluated_queries"],
            "positive_queries": graph["positive_queries"],
            "text_baseline": benchmark["text_baseline"],
            "graph_rag": graph,
            "safety": safety,
            "gates": benchmark["gates"],
        }
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Graph RAG regression or one-time blind benchmark"
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--quality-report", type=Path, default=DEFAULT_QUALITY_REPORT)
    parser.add_argument("--update-quality", action="store_true")
    parser.add_argument("--run-ablations", action="store_true")
    parser.add_argument("--ablation-output", type=Path)
    args = parser.parse_args()
    benchmark = run_benchmark(args.gold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if args.update_quality:
        update_quality_report(args.quality_report, benchmark, args.output)
    if args.run_ablations:
        ablations = run_ablation_suite(args.gold)
        ablation_output = args.ablation_output or args.output.with_name("graph_rag_ablation.json")
        ablation_output.parent.mkdir(parents=True, exist_ok=True)
        ablation_output.write_text(
            json.dumps(ablations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                key: benchmark[key]
                for key in ("dataset", "text_baseline", "graph_rag", "safety", "rollout_ready")
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
