"""Materialize normalized logic topics and versioned topic-ranking priors from existing theses."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.domain import LogicTopicRecord, LogicTopicRelationRecord
from app.db.models.core import Evidence, Hypothesis, HypothesisMetricMap, MetricObservation, Thesis
from app.ranking.builder import PriorInput, build_snapshot
from app.ranking.features import PriorFeatures


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _ratio(value, default: float = 0.0) -> float:
    if value is None:
        return default
    return max(0.0, min(float(value), 1.0))


def _normalized_statement(thesis: Thesis) -> str:
    text = re.sub(r"\s+", " ", (thesis.core_view or thesis.title).strip())
    return text[:1200]


def _recency(disclosed_at: datetime | None, as_of: datetime) -> float:
    if disclosed_at is None:
        return 0.4
    age_days = max((as_of - disclosed_at).days, 0)
    return max(0.1, 0.5 ** (age_days / 365.0))


def _importance(value: str) -> float:
    return {"高": 1.0, "核心": 1.0, "中": 0.7, "一般": 0.6, "低": 0.4}.get(value, 0.6)


def _relation(
    topic_id: str,
    object_type: str,
    object_id: str,
    relation: str,
    *,
    confidence: float,
    reason: str,
    citations: list[str] | None = None,
    valid_from: datetime | None = None,
) -> LogicTopicRelationRecord:
    return LogicTopicRelationRecord(
        relation_id=_stable_id("LTR", topic_id, object_type, object_id, relation),
        topic_id=topic_id,
        object_type=object_type,
        object_id=object_id,
        relation=relation,
        confidence=Decimal(str(round(confidence, 6))),
        source="deterministic_v1",
        reason=reason,
        citation_locators=citations or [],
        valid_from=valid_from,
    )


def materialize(
    session,
    uow,
    *,
    security_id: str,
    direction: str,
    horizon: str,
    as_of: datetime,
    ranker_version: str,
    judgements: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    theses = session.scalars(
        select(Thesis)
        .where(
            Thesis.security_id == security_id,
            Thesis.direction == direction,
            Thesis.established_on <= as_of.date(),
            Thesis.status.notin_(("已归档", "已失效")),
        )
        .order_by(Thesis.thesis_id)
    ).all()
    topics: list[LogicTopicRecord] = []
    relations: list[LogicTopicRelationRecord] = []
    prior_inputs: list[PriorInput] = []
    clustered_hypotheses: dict[str, list[Hypothesis]] = {}
    thesis_by_id = {row.thesis_id: row for row in theses}
    for thesis in theses:
        statement = _normalized_statement(thesis)
        topic_id = _stable_id("TOPIC", security_id, direction, horizon, statement, "v1")
        hypotheses = session.scalars(
            select(Hypothesis).where(Hypothesis.thesis_id == thesis.thesis_id)
        ).all()
        hypothesis_ids = [row.hypothesis_id for row in hypotheses]
        for hypothesis in hypotheses:
            cluster_name = (hypothesis.name or hypothesis.hypothesis_type or "核心假设").strip()
            clustered_hypotheses.setdefault(cluster_name, []).append(hypothesis)
        evidences = session.scalars(
            select(Evidence).where(
                Evidence.thesis_id == thesis.thesis_id,
                Evidence.disclosed_at <= as_of,
            )
        ).all()
        mappings = (
            session.scalars(
                select(HypothesisMetricMap).where(
                    HypothesisMetricMap.hypothesis_id.in_(hypothesis_ids)
                )
            ).all()
            if hypothesis_ids
            else []
        )
        metric_ids = sorted({row.metric_id for row in mappings})
        observation_count = (
            session.scalar(
                select(func.count())
                .select_from(MetricObservation)
                .where(
                    MetricObservation.security_id == security_id,
                    MetricObservation.metric_id.in_(metric_ids),
                    MetricObservation.observation_date <= as_of.date(),
                )
            )
            if metric_ids
            else 0
        )
        support = [row for row in evidences if str(row.direction) == "支持"]
        conflicts = [row for row in evidences if str(row.direction) == "冲突"]
        direct = [
            row
            for row in evidences
            if row.is_direct
            or (row.source_document_id and row.evidence_locator and "#" in row.evidence_locator)
        ]
        strengths = [
            _ratio(row.strength_score, _ratio(row.ai_confidence, 0.55)) for row in evidences
        ]
        evidence_strength = min(
            1.0,
            (sum(strengths) / len(strengths) if strengths else 0.35)
            + min(
                len({row.source_document_id for row in evidences if row.source_document_id}) / 5,
                0.25,
            ),
        )
        materiality = sum(_importance(str(row.importance)) for row in hypotheses) / max(
            len(hypotheses), 1
        )
        mapped_hypotheses = {row.hypothesis_id for row in mappings}
        verifiability = 0.35 + 0.4 * len(mapped_hypotheses) / max(len(hypotheses), 1)
        if mappings and all(
            row.validation_rule or row.invalidation_rule or row.invalidation_threshold is not None
            for row in mappings
        ):
            verifiability += 0.25
        verifiability *= min(len(metric_ids) / 2, 1.0)
        persistence = min(
            1.0,
            0.45
            + 0.45 * min(int(observation_count or 0) / 8, 1.0)
            + (0.1 if any(row.observation_window for row in hypotheses) else 0.0),
        )
        causal = 0.45 + 0.35 * (
            sum(bool(row.transmission_path) for row in evidences) / max(len(evidences), 1)
        )
        causal += 0.2 if metric_ids else 0.0
        recency = max((_recency(row.disclosed_at, as_of) for row in evidences), default=0.4)
        conflict_coverage = 1.0 if conflicts else 0.35
        conflict_severity = max((_ratio(row.strength_score, 0.6) for row in conflicts), default=0.0)
        features = PriorFeatures(
            business_materiality=min(materiality, 1.0),
            evidence_strength=evidence_strength,
            persistence=persistence,
            verifiability=min(verifiability, 1.0),
            company_specificity=0.9,
            causal_strength=min(causal, 1.0),
            recency=recency,
            conflict_attention=conflict_coverage,
            unresolved_conflict_severity=conflict_severity,
            low_value_penalty=1.0 if len(metric_ids) < 2 or not direct else 0.0,
        )
        citation_locators = sorted(
            {row.evidence_locator for row in evidences if row.evidence_locator}
        )
        topics.append(
            LogicTopicRecord(
                topic_id=topic_id,
                security_id=security_id,
                name=thesis.title,
                normalized_statement=statement,
                direction=direction,
                horizon=horizon,
                source_thesis_ids=[thesis.thesis_id],
                metadata={
                    "hypothesis_count": len(hypotheses),
                    "metric_count": len(metric_ids),
                    "support_count": len(support),
                    "conflict_count": len(conflicts),
                },
            )
        )
        relations.append(
            _relation(
                topic_id,
                "thesis",
                thesis.thesis_id,
                "来源",
                confidence=1.0,
                reason="由现有正式投资逻辑标准化",
            )
        )
        for row in hypotheses:
            relations.append(
                _relation(
                    topic_id,
                    "hypothesis",
                    row.hypothesis_id,
                    "验证",
                    confidence=0.9,
                    reason="核心假设属于来源投资逻辑",
                )
            )
        for metric_id in metric_ids:
            relations.append(
                _relation(
                    topic_id,
                    "metric",
                    metric_id,
                    "验证",
                    confidence=0.85,
                    reason="通过假设指标映射关联",
                )
            )
        for row in evidences:
            relation = (
                str(row.direction) if str(row.direction) in {"支持", "冲突", "中性"} else "中性"
            )
            relations.append(
                _relation(
                    topic_id,
                    "evidence",
                    row.evidence_id,
                    relation,
                    confidence=_ratio(row.ai_confidence, 0.7),
                    reason="通过投资逻辑和假设关联",
                    citations=[row.evidence_locator] if row.evidence_locator else [],
                    valid_from=row.disclosed_at,
                )
            )
            if row.evidence_locator:
                relations.append(
                    _relation(
                        topic_id,
                        "document_segment",
                        row.evidence_locator,
                        relation,
                        confidence=_ratio(row.ai_confidence, 0.7),
                        reason="证据引用切片",
                        citations=[row.evidence_locator],
                        valid_from=row.disclosed_at,
                    )
                )
        reasons = ["THESIS_NORMALIZED", "COMPANY_SCOPED", "AS_OF_VALID"]
        if metric_ids:
            reasons.append("METRIC_VERIFIABLE")
        if direct:
            reasons.append("DIRECT_EVIDENCE")
        if len(metric_ids) >= 2 and direct and verifiability >= 0.6:
            reasons.append("PRIMARY_TOPIC_ELIGIBLE")
        else:
            reasons.append("PRIMARY_TOPIC_GATE_FAILED")
        if conflicts:
            reasons.append("COUNTER_EVIDENCE_COVERED")
        prior_inputs.append(
            PriorInput(
                object_type="logic_topic",
                object_id=topic_id,
                features=features,
                reason_codes=tuple(reasons),
                citation_locators=tuple(citation_locators),
                content=statement,
            )
        )

    # A company's quarterly theses are longitudinal versions. Stable hypothesis names
    # represent genuinely different research angles and become comparable sub-topics.
    for cluster_name, hypotheses in clustered_hypotheses.items():
        hypothesis_ids = [row.hypothesis_id for row in hypotheses]
        source_thesis_ids = sorted({row.thesis_id for row in hypotheses})
        latest = max(
            hypotheses,
            key=lambda row: (
                thesis_by_id[row.thesis_id].established_on,
                row.hypothesis_id,
            ),
        )
        statement = re.sub(r"\s+", " ", latest.statement.strip())[:1200]
        topic_id = _stable_id(
            "TOPIC", security_id, direction, horizon, "hypothesis-cluster", cluster_name, "v1"
        )
        evidences = session.scalars(
            select(Evidence).where(
                Evidence.hypothesis_id.in_(hypothesis_ids),
                Evidence.disclosed_at <= as_of,
            )
        ).all()
        mappings = session.scalars(
            select(HypothesisMetricMap).where(HypothesisMetricMap.hypothesis_id.in_(hypothesis_ids))
        ).all()
        metric_ids = sorted({row.metric_id for row in mappings})
        observation_count = (
            session.scalar(
                select(func.count())
                .select_from(MetricObservation)
                .where(
                    MetricObservation.security_id == security_id,
                    MetricObservation.metric_id.in_(metric_ids),
                    MetricObservation.observation_date <= as_of.date(),
                )
            )
            if metric_ids
            else 0
        )
        support = [row for row in evidences if str(row.direction) == "支持"]
        conflicts = [row for row in evidences if str(row.direction) == "冲突"]
        direct = [
            row
            for row in evidences
            if row.is_direct
            or (row.source_document_id and row.evidence_locator and "#" in row.evidence_locator)
        ]
        strengths = [
            _ratio(row.strength_score, _ratio(row.ai_confidence, 0.55)) for row in evidences
        ]
        evidence_strength = min(
            1.0,
            (sum(strengths) / len(strengths) if strengths else 0.35)
            + min(
                len({row.source_document_id for row in evidences if row.source_document_id}) / 5,
                0.25,
            ),
        )
        materiality = sum(_importance(str(row.importance)) for row in hypotheses) / max(
            len(hypotheses), 1
        )
        mapped_hypotheses = {row.hypothesis_id for row in mappings}
        verifiability = 0.35 + 0.4 * len(mapped_hypotheses) / max(len(hypotheses), 1)
        if mappings and all(
            row.validation_rule or row.invalidation_rule or row.invalidation_threshold is not None
            for row in mappings
        ):
            verifiability += 0.25
        verifiability *= min(len(metric_ids) / 2, 1.0)
        persistence = min(
            1.0,
            0.45
            + 0.45 * min(int(observation_count or 0) / 8, 1.0)
            + (0.1 if len(source_thesis_ids) >= 3 else 0.0),
        )
        causal = 0.45 + 0.35 * (
            sum(bool(row.transmission_path) for row in evidences) / max(len(evidences), 1)
        )
        causal += 0.2 if metric_ids else 0.0
        recency = max((_recency(row.disclosed_at, as_of) for row in evidences), default=0.4)
        conflict_coverage = 1.0 if conflicts else 0.35
        conflict_severity = max((_ratio(row.strength_score, 0.6) for row in conflicts), default=0.0)
        features = PriorFeatures(
            business_materiality=min(materiality, 1.0),
            evidence_strength=evidence_strength,
            persistence=persistence,
            verifiability=min(verifiability, 1.0),
            company_specificity=0.85,
            causal_strength=min(causal, 1.0),
            recency=recency,
            conflict_attention=conflict_coverage,
            unresolved_conflict_severity=conflict_severity,
            low_value_penalty=1.0 if len(metric_ids) < 2 or not direct else 0.0,
        )
        citation_locators = sorted(
            {row.evidence_locator for row in evidences if row.evidence_locator}
        )
        topics.append(
            LogicTopicRecord(
                topic_id=topic_id,
                security_id=security_id,
                name=cluster_name,
                normalized_statement=statement,
                direction=direction,
                horizon=horizon,
                source_thesis_ids=source_thesis_ids,
                metadata={
                    "topic_kind": "hypothesis_cluster",
                    "hypothesis_count": len(hypotheses),
                    "metric_count": len(metric_ids),
                    "support_count": len(support),
                    "conflict_count": len(conflicts),
                },
            )
        )
        for thesis_id in source_thesis_ids:
            relations.append(
                _relation(
                    topic_id,
                    "thesis",
                    thesis_id,
                    "来源",
                    confidence=0.9,
                    reason="由跨季度稳定核心假设簇派生",
                )
            )
        for row in hypotheses:
            relations.append(
                _relation(
                    topic_id,
                    "hypothesis",
                    row.hypothesis_id,
                    "验证",
                    confidence=1.0,
                    reason="核心假设属于该稳定主题簇",
                )
            )
        for metric_id in metric_ids:
            relations.append(
                _relation(
                    topic_id,
                    "metric",
                    metric_id,
                    "验证",
                    confidence=0.9,
                    reason="通过主题簇内假设指标映射关联",
                )
            )
        for row in evidences:
            relation = (
                str(row.direction) if str(row.direction) in {"支持", "冲突", "中性"} else "中性"
            )
            relations.append(
                _relation(
                    topic_id,
                    "evidence",
                    row.evidence_id,
                    relation,
                    confidence=_ratio(row.ai_confidence, 0.7),
                    reason="通过主题簇内核心假设关联",
                    citations=[row.evidence_locator] if row.evidence_locator else [],
                    valid_from=row.disclosed_at,
                )
            )
            if row.evidence_locator:
                relations.append(
                    _relation(
                        topic_id,
                        "document_segment",
                        row.evidence_locator,
                        relation,
                        confidence=_ratio(row.ai_confidence, 0.7),
                        reason="主题证据引用切片",
                        citations=[row.evidence_locator],
                        valid_from=row.disclosed_at,
                    )
                )
        reasons = ["HYPOTHESIS_CLUSTERED", "COMPANY_SCOPED", "AS_OF_VALID"]
        if len(source_thesis_ids) >= 3:
            reasons.append("CROSS_PERIOD_PERSISTENT")
        if metric_ids:
            reasons.append("METRIC_VERIFIABLE")
        if direct:
            reasons.append("DIRECT_EVIDENCE")
        if len(metric_ids) >= 2 and direct and verifiability >= 0.6:
            reasons.append("PRIMARY_TOPIC_ELIGIBLE")
        else:
            reasons.append("PRIMARY_TOPIC_GATE_FAILED")
        if conflicts:
            reasons.append("COUNTER_EVIDENCE_COVERED")
        prior_inputs.append(
            PriorInput(
                object_type="logic_topic",
                object_id=topic_id,
                features=features,
                reason_codes=tuple(reasons),
                citation_locators=tuple(citation_locators),
                content=statement,
            )
        )
    merged_topics: dict[str, LogicTopicRecord] = {}
    for topic in topics:
        existing = merged_topics.get(topic.topic_id)
        if existing is None:
            merged_topics[topic.topic_id] = topic
            continue
        merged_topics[topic.topic_id] = LogicTopicRecord(
            **{
                **existing.__dict__,
                "source_thesis_ids": sorted(
                    set(existing.source_thesis_ids) | set(topic.source_thesis_ids)
                ),
                "metadata": {
                    key: int(existing.metadata.get(key, 0)) + int(topic.metadata.get(key, 0))
                    for key in set(existing.metadata) | set(topic.metadata)
                },
            }
        )
    merged_relations = {row.relation_id: row for row in relations}
    merged_inputs: dict[str, PriorInput] = {}
    for row in prior_inputs:
        existing = merged_inputs.get(row.object_id)
        if existing is None:
            merged_inputs[row.object_id] = row
            continue
        combined_features = PriorFeatures(
            **{
                key: max(existing.features.as_dict()[key], row.features.as_dict()[key])
                for key in existing.features.as_dict()
            }
        )
        merged_inputs[row.object_id] = PriorInput(
            object_type=row.object_type,
            object_id=row.object_id,
            features=combined_features,
            reason_codes=tuple(dict.fromkeys((*existing.reason_codes, *row.reason_codes))),
            citation_locators=tuple(
                dict.fromkeys((*existing.citation_locators, *row.citation_locators))
            ),
            content=existing.content,
        )
    topics = list(merged_topics.values())
    relations = list(merged_relations.values())
    prior_inputs = list(merged_inputs.values())
    if judgements:
        reviewed_inputs = []
        for row in prior_inputs:
            judgement = judgements.get(row.object_id)
            if judgement is None:
                reviewed_inputs.append(row)
                continue
            review_codes = list(judgement.get("reason_codes", []))
            if judgement.get("primary_approved") is False:
                review_codes.append("MODEL_PRIMARY_REJECTED")
            elif judgement.get("primary_approved") is True:
                review_codes.append("MODEL_PRIMARY_APPROVED")
            reviewed_inputs.append(
                replace(
                    row,
                    judge_score=float(judgement["score"]),
                    judge_confidence=float(judgement.get("confidence", 0.7)),
                    reason_codes=tuple(dict.fromkeys((*row.reason_codes, *review_codes))),
                    citation_locators=tuple(
                        dict.fromkeys(
                            (*row.citation_locators, *judgement.get("citation_locators", []))
                        )
                    ),
                )
            )
        prior_inputs = reviewed_inputs
    uow.ranking.upsert_topics(topics)
    uow.ranking.upsert_topic_relations(relations)
    snapshot = (
        build_snapshot(
            uow,
            security_id=security_id,
            direction=direction,
            horizon=horizon,
            as_of=as_of,
            ranker_version=ranker_version,
            feature_version="logic-topic-features-v1",
            inputs=prior_inputs,
        )
        if prior_inputs
        else None
    )
    return {
        "security_id": security_id,
        "topics": len(topics),
        "relations": len(relations),
        "snapshot_id": snapshot.snapshot_id if snapshot else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--security-id", action="append", dest="security_ids")
    parser.add_argument("--direction", help="留空时按数据库中每家公司的现有方向分别构建")
    parser.add_argument("--horizon", default="12M")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--ranker-version", default="logic-topic-prior-v1")
    parser.add_argument(
        "--offline-judgements",
        type=Path,
        help="当前模型或研究员导出的主题复核 JSON；包含 topic_id、score、confidence 与引用。",
    )
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of)
    if as_of.tzinfo is None:
        parser.error("--as-of 必须包含时区")
    from app.db.repositories import build_uow
    from app.db.session import session_scope

    with session_scope() as session:
        judgements = None
        if args.offline_judgements:
            payload = json.loads(args.offline_judgements.read_text(encoding="utf-8"))
            rows = payload.get("judgements", payload) if isinstance(payload, dict) else payload
            if not isinstance(rows, list):
                parser.error("--offline-judgements 必须为数组或包含 judgements 数组的对象")
            judgements = {str(row["topic_id"]): row for row in rows}
        scope_query = select(Thesis.security_id, Thesis.direction).distinct()
        if args.security_ids:
            scope_query = scope_query.where(Thesis.security_id.in_(args.security_ids))
        if args.direction:
            scope_query = scope_query.where(Thesis.direction == args.direction)
        scopes = session.execute(scope_query).all()
        reports = [
            materialize(
                session,
                build_uow(session),
                security_id=security_id,
                direction=direction,
                horizon=args.horizon,
                as_of=as_of,
                ranker_version=args.ranker_version,
                judgements=judgements,
            )
            for security_id, direction in scopes
        ]
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
