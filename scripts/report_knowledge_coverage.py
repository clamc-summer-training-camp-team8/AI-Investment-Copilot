"""Generate a nine-company RAG coverage and supplementation-priority report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import cast

from sqlalchemy import func, select

from app.db.models.core import (
    Document,
    DocumentSegment,
    Evidence,
    Hypothesis,
    HypothesisMetricMap,
    MetricObservation,
    Security,
    Thesis,
)
from app.db.session import session_scope

PILOT_INDUSTRIES = ("芯片半导体", "医药", "新能源汽车")


def _count(session, statement) -> int:
    return int(session.scalar(statement) or 0)


def _company_row(session, security: Security) -> dict[str, object]:
    security_id = security.security_id
    thesis_ids = select(Thesis.thesis_id).where(Thesis.security_id == security_id)
    core_ids = select(Hypothesis.hypothesis_id).where(
        Hypothesis.thesis_id.in_(thesis_ids), Hypothesis.importance == "核心"
    )
    document_ids = select(Document.document_id).where(
        Document.security_id == security_id, Document.deleted_at.is_(None)
    )
    documents = _count(session, select(func.count()).select_from(document_ids.subquery()))
    segments = _count(
        session,
        select(func.count())
        .select_from(DocumentSegment)
        .where(DocumentSegment.document_id.in_(document_ids)),
    )
    title_like = _count(
        session,
        select(func.count())
        .select_from(DocumentSegment)
        .where(
            DocumentSegment.document_id.in_(document_ids),
            (DocumentSegment.content.like("公告标题：%"))
            | (func.length(DocumentSegment.content) < 80),
        ),
    )
    full_segments = max(0, segments - title_like)
    theses = _count(
        session, select(func.count()).select_from(Thesis).where(Thesis.security_id == security_id)
    )
    hypotheses = _count(
        session,
        select(func.count()).select_from(Hypothesis).where(Hypothesis.thesis_id.in_(thesis_ids)),
    )
    core_hypotheses = _count(session, select(func.count()).select_from(core_ids.subquery()))
    mapped_core = _count(
        session,
        select(func.count(func.distinct(HypothesisMetricMap.hypothesis_id))).where(
            HypothesisMetricMap.hypothesis_id.in_(core_ids)
        ),
    )
    evidence = _count(
        session,
        select(func.count()).select_from(Evidence).where(Evidence.security_id == security_id),
    )
    non_title_evidence = _count(
        session,
        select(func.count())
        .select_from(Evidence)
        .where(
            Evidence.security_id == security_id,
            Evidence.fact_excerpt.is_not(None),
            ~Evidence.fact_excerpt.like("公告标题：%"),
        ),
    )
    searchable_evidence = _count(
        session,
        select(func.count())
        .select_from(Evidence)
        .where(
            Evidence.security_id == security_id,
            Evidence.source_document_id.is_not(None),
            Evidence.evidence_locator.is_not(None),
            Evidence.evidence_locator.in_(
                select(DocumentSegment.locator).where(
                    DocumentSegment.document_id == Evidence.source_document_id
                )
            ),
        ),
    )
    confirmed_evidence = _count(
        session,
        select(func.count())
        .select_from(Evidence)
        .where(Evidence.security_id == security_id, Evidence.confirmation_status == "已确认"),
    )
    support = _count(
        session,
        select(func.count())
        .select_from(Evidence)
        .where(Evidence.security_id == security_id, Evidence.direction == "支持"),
    )
    conflict = _count(
        session,
        select(func.count())
        .select_from(Evidence)
        .where(Evidence.security_id == security_id, Evidence.direction == "冲突"),
    )
    non_title_conflict = _count(
        session,
        select(func.count())
        .select_from(Evidence)
        .where(
            Evidence.security_id == security_id,
            Evidence.direction == "冲突",
            Evidence.fact_excerpt.is_not(None),
            ~Evidence.fact_excerpt.like("公告标题：%"),
        ),
    )
    observations = _count(
        session,
        select(func.count())
        .select_from(MetricObservation)
        .where(MetricObservation.security_id == security_id),
    )
    score = round(
        min(documents / 50, 1) * 20
        + min(segments / 150, 1) * 20
        + min(full_segments / max(segments, 1) / 0.7, 1) * 15
        + (mapped_core / max(core_hypotheses, 1)) * 15
        + min(support / max(core_hypotheses * 3, 1), 1) * 8
        + min(conflict / max(core_hypotheses, 1), 1) * 7
        + min(observations / 24, 1) * 15,
        1,
    )
    gaps: list[str] = []
    if full_segments / max(segments, 1) < 0.7:
        gaps.append("补公告/报告正文与事实切片")
    if mapped_core < core_hypotheses:
        gaps.append("补核心假设—指标映射")
    if conflict < core_hypotheses:
        gaps.append("补反证与风险事件")
    if non_title_conflict == 0:
        gaps.append("补可检索的非标题型反证事实")
    if observations < 24:
        gaps.append("补至少8个季度指标序列")
    if documents < 50:
        gaps.append("补经营、行业和竞品来源")
    priority = "P0" if score < 45 else "P1" if score < 70 else "P2"
    return {
        "security_id": security_id,
        "company": security.name,
        "industry": security.industry or "未分类",
        "score": score,
        "priority": priority,
        "documents": documents,
        "segments": segments,
        "full_segments": full_segments,
        "title_like_segments": title_like,
        "theses": theses,
        "hypotheses": hypotheses,
        "core_hypotheses": core_hypotheses,
        "mapped_core_hypotheses": mapped_core,
        "evidence": evidence,
        "non_title_evidence": non_title_evidence,
        "searchable_evidence": searchable_evidence,
        "evidence_traceability_rate": round(searchable_evidence / max(evidence, 1), 4),
        "confirmed_evidence": confirmed_evidence,
        "candidate_evidence": evidence - confirmed_evidence,
        "support_evidence": support,
        "conflict_evidence": conflict,
        "non_title_conflict_evidence": non_title_conflict,
        "metric_observations": observations,
        "gaps": gaps,
    }


def _markdown(rows: list[dict[str, object]]) -> str:
    industry_counts = Counter(str(row["industry"]) for row in rows)
    lines = [
        "# 九家公司知识库覆盖度报告",
        "",
        "统计口径：当前 PostgreSQL 已入库且未删除对象。评分用于补库优先级，不代表投资结论。",
        "",
        f"覆盖范围：{len(rows)} 家公司，{len(industry_counts)} 个行业。",
        "",
        "| 行业 | 公司 | 评分 | 优先级 | 文档 | 切片（正文/标题型） | 逻辑/核心假设 | 核心假设映射 | 可追溯证据/全部 | 非标题证据 | 支持/反证（非标题反证） | 指标观测 |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {industry} | {company} | {score} | {priority} | {documents} | "
            "{segments}（{full_segments}/{title_like_segments}） | {theses}/{core_hypotheses} | "
            "{mapped_core_hypotheses}/{core_hypotheses} | {searchable_evidence}/{evidence} | "
            "{non_title_evidence} | {support_evidence}/{conflict_evidence}（{non_title_conflict_evidence}） | "
            "{metric_observations} |".format(**row)
        )
    lines += ["", "## 补库优先级", ""]
    for row in sorted(
        rows, key=lambda item: (str(item["priority"]), float(cast(float, item["score"])))
    ):
        gaps = "；".join(cast(list[str], row["gaps"])) or "当前口径无硬缺口"
        lines.append(
            f"- **{row['priority']}｜{row['company']}（{row['security_id']}，{row['score']}分）**：{gaps}。"
        )
    lines += [
        "",
        "## 执行顺序",
        "",
        "1. 先处理所有 P0 公司：补正文、核心假设映射、反证和指标序列。",
        "2. 每个行业选一家公司完成闭环后，再复制统一模板到同业另外两家。",
        "3. 新材料入库后重跑本报告；评分达到 70 分以上才进入排序先验的正式试用候选。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analytics/experiments/nine-company-knowledge-coverage.md"),
    )
    parser.add_argument("--include-unscoped", action="store_true")
    args = parser.parse_args()
    with session_scope() as session:
        statement = select(Security).order_by(Security.industry, Security.security_id)
        if not args.include_unscoped:
            statement = statement.where(Security.industry.in_(PILOT_INDUSTRIES))
        securities = session.scalars(statement).all()
        rows = [_company_row(session, security) for security in securities]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(_markdown(rows), encoding="utf-8")
    args.output.with_suffix(".json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"companies": len(rows), "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
