"""从结构化 JSON 或现有 PostgreSQL 知识对象构建排序先验快照。"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.core.config import settings
from app.ranking.builder import PriorInput, build_snapshot
from app.ranking.features import PriorFeatures, score_for_object

LOW_VALUE_PATTERNS = (
    "股东大会",
    "法律意见书",
    "律师事务所",
    "会议通知",
    "会议决议",
    "内幕信息知情人",
    "投资者关系管理制度",
    "募集资金管理制度",
)


def _content_key(content: str) -> str:
    return re.sub(r"[\W_\d]+", "", content).lower()[:160]


def _ratio(value, default: float) -> float:
    return max(0.0, min(float(value), 1.0)) if value is not None else default


def _database_inputs(session, *, security_id: str, as_of: datetime) -> list[PriorInput]:
    """把已入库段落投影为 V1 文档片段先验；只使用 as_of 时点可见数据。"""
    from sqlalchemy import select

    from app.db.models.core import Document, DocumentSegment, Evidence, HypothesisMetricMap

    rows = session.execute(
        select(DocumentSegment, Document)
        .join(Document, Document.document_id == DocumentSegment.document_id)
        .where(
            Document.security_id == security_id,
            Document.deleted_at.is_(None),
            Document.published_at <= as_of,
        )
        .order_by(Document.published_at, DocumentSegment.locator)
    ).all()
    inputs: list[PriorInput] = []
    seen_content: set[str] = set()
    for segment, document in rows:
        evidences = session.scalars(
            select(Evidence).where(Evidence.evidence_locator == segment.locator)
        ).all()
        mapping_count = 0
        for evidence in evidences:
            mapping_count += len(
                session.scalars(
                    select(HypothesisMetricMap).where(
                        HypothesisMetricMap.hypothesis_id == evidence.hypothesis_id
                    )
                ).all()
            )
        strongest = max(
            (
                _ratio(evidence.strength_score, _ratio(evidence.ai_confidence, 0.65))
                for evidence in evidences
            ),
            default=0.5,
        )
        is_public_source = bool(
            (document.raw_path or "").startswith("https://")
            or document.source_id
            or document.visibility_label == "公开"
        )
        length_score = min(len(segment.content.strip()) / 160, 1.0)
        content_key = _content_key(segment.content)
        is_duplicate = bool(content_key and content_key in seen_content)
        seen_content.add(content_key)
        is_low_value = any(pattern in segment.content for pattern in LOW_VALUE_PATTERNS)
        features = PriorFeatures(
            business_materiality=0.85 if evidences else 0.55,
            evidence_strength=strongest,
            persistence=0.7,
            verifiability=1.0 if mapping_count else 0.55,
            company_specificity=1.0,
            causal_strength=0.8 if evidences else 0.5,
            recency=0.7,
            conflict_attention=(
                0.9 if any(str(evidence.direction) == "冲突" for evidence in evidences) else 0.1
            ),
            source_authority=0.9 if is_public_source else 0.6,
            direct_relevance=0.95 if evidences else 0.55,
            completeness=0.6 + 0.4 * length_score,
            temporal_validity=1.0,
            novelty=0.2 if is_duplicate else 0.8,
            traceability=1.0,
            statement_clarity=0.6 + 0.4 * length_score,
            low_value_penalty=1.0 if is_low_value else (0.35 if is_duplicate else 0.0),
        )
        reason_codes = ["SECURITY_MATCH", "AS_OF_VALID", "TRACEABLE_LOCATOR"]
        if evidences:
            reason_codes.append("EVIDENCE_LINKED")
        if mapping_count:
            reason_codes.append("METRIC_VERIFIABLE")
        if is_low_value:
            reason_codes.append("LOW_VALUE_DISCLOSURE")
        if is_duplicate:
            reason_codes.append("NEAR_DUPLICATE")
        inputs.append(
            PriorInput(
                object_type="document_segment",
                object_id=segment.locator,
                features=features,
                reason_codes=tuple(reason_codes),
                citation_locators=(segment.locator,),
                content=segment.content,
            )
        )
    return inputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--security-id", required=True)
    parser.add_argument("--direction", default="看多")
    parser.add_argument("--horizon", default="12M")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--ranker-version", default="thesis-prior-v1")
    parser.add_argument("--feature-version", default="prior-features-v1")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument(
        "--offline-judgements",
        type=Path,
        help="当前对话或人工复核生成的 judgement JSON；不得与 --judge 同用",
    )
    args = parser.parse_args()
    if bool(args.input) == bool(args.from_db):
        parser.error("必须且只能选择 --input 或 --from-db")
    if args.judge and args.offline_judgements:
        parser.error("--judge 与 --offline-judgements 不能同时使用")
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")
    from app.db.repositories import build_uow
    from app.db.session import session_scope

    with session_scope() as session:
        if args.from_db:
            inputs = _database_inputs(session, security_id=args.security_id, as_of=as_of)
        else:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            inputs = [
                PriorInput(
                    object_type=row["object_type"],
                    object_id=row["object_id"],
                    features=PriorFeatures(**row.get("feature_scores", {})),
                    reason_codes=tuple(row.get("reason_codes", [])),
                    citation_locators=tuple(row.get("citation_locators", [])),
                    judge_score=row.get("judge_score"),
                    judge_confidence=row.get("judge_confidence"),
                )
                for row in payload
            ]
        if not inputs:
            raise SystemExit(f"{args.security_id} 在 {args.as_of} 前没有可构建的文档片段")
        if args.judge:
            if not settings.ranking_judge_enabled:
                raise SystemExit("--judge 要求配置 RANKING_JUDGE_ENABLED=true")
            from app.ranking.openai_judge import OpenAIRankingJudge

            judge_limit = settings.ranking_judge_candidate_limit
            judge_inputs = sorted(
                inputs,
                key=lambda row: (-score_for_object(row.object_type, row.features), row.object_id),
            )[:judge_limit]
            judgements = OpenAIRankingJudge(settings).judge(
                [
                    {
                        "object_id": row.object_id,
                        "content": row.content[:1200],
                        "base_score": score_for_object(row.object_type, row.features),
                        "reason_codes": list(row.reason_codes),
                        "citation_locators": list(row.citation_locators),
                    }
                    for row in judge_inputs
                ]
            )
            by_id = {row.object_id: row for row in judgements}
            inputs = [
                replace(
                    row,
                    judge_score=by_id[row.object_id].score,
                    judge_confidence=by_id[row.object_id].confidence,
                    reason_codes=tuple(
                        dict.fromkeys((*row.reason_codes, *by_id[row.object_id].reason_codes))
                    ),
                )
                if row.object_id in by_id
                else row
                for row in inputs
            ]
        elif args.offline_judgements:
            payload = json.loads(args.offline_judgements.read_text(encoding="utf-8"))
            rows = payload.get("ranking", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                raise SystemExit("离线复核文件必须为数组或含 ranking 数组的对象")
            offline_by_id = {
                str(row["object_id"]): row
                for row in rows
                if isinstance(row, dict) and "object_id" in row
            }
            known_ids = {row.object_id for row in inputs}
            unknown_ids = set(offline_by_id) - known_ids
            if unknown_ids:
                raise SystemExit(f"离线复核包含未知候选: {sorted(unknown_ids)[:3]}")
            inputs = [
                replace(
                    row,
                    judge_score=float(offline_by_id[row.object_id]["score"]),
                    judge_confidence=float(offline_by_id[row.object_id].get("confidence", 0.7)),
                    reason_codes=tuple(
                        dict.fromkeys(
                            (
                                *row.reason_codes,
                                *offline_by_id[row.object_id].get("reason_codes", []),
                            )
                        )
                    ),
                    citation_locators=tuple(
                        dict.fromkeys(
                            (
                                *row.citation_locators,
                                *offline_by_id[row.object_id].get("citation_locators", []),
                            )
                        )
                    ),
                )
                if row.object_id in offline_by_id
                else row
                for row in inputs
            ]
        uow = build_uow(session)
        snapshot = build_snapshot(
            uow,
            security_id=args.security_id,
            direction=args.direction,
            horizon=args.horizon,
            as_of=as_of,
            ranker_version=args.ranker_version,
            feature_version=args.feature_version,
            inputs=inputs,
            judge_model_version=(
                settings.ranking_judge_model_version
                if args.judge
                else ("gpt-5.6-terra-offline" if args.offline_judgements else None)
            ),
            prompt_version=(
                "ranking-judge-v1"
                if args.judge
                else ("ranking-judge-offline-v1" if args.offline_judgements else None)
            ),
            judge_weight=settings.ranking_judge_weight,
        )
    print(
        json.dumps(
            {"snapshot_id": snapshot.snapshot_id, "status": snapshot.status, "items": len(inputs)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
