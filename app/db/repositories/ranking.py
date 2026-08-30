from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.domain import (
    LogicTopicRecord,
    LogicTopicRelationRecord,
    RankingPriorItemRecord,
    RankingPriorSnapshotRecord,
)
from app.db.models.ranking import (
    LogicTopic,
    LogicTopicRelation,
    RankingPriorItem,
    RankingPriorSnapshot,
)


class SqlRankingPriorRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _snapshot(row: RankingPriorSnapshot) -> RankingPriorSnapshotRecord:
        return RankingPriorSnapshotRecord(
            snapshot_id=row.snapshot_id,
            security_id=row.security_id,
            direction=row.direction,
            horizon=row.horizon,
            as_of=row.as_of,
            ranker_version=row.ranker_version,
            feature_version=row.feature_version,
            status=row.status,
            generator_model_version=row.generator_model_version,
            judge_model_version=row.judge_model_version,
            prompt_version=row.prompt_version,
            metadata=dict(row.metadata_json or {}),
            created_at=row.created_at,
        )

    @staticmethod
    def _item(row: RankingPriorItem) -> RankingPriorItemRecord:
        return RankingPriorItemRecord(
            snapshot_id=row.snapshot_id,
            object_type=row.object_type,
            object_id=row.object_id,
            base_rank=row.base_rank,
            base_score=row.base_score,
            judge_rank=row.judge_rank,
            judge_score=row.judge_score,
            judge_confidence=row.judge_confidence,
            final_rank=row.final_rank,
            final_score=row.final_score,
            feature_scores=dict(row.feature_scores or {}),
            reason_codes=list(row.reason_codes or []),
            citation_locators=list(row.citation_locators or []),
            status=row.status,
        )

    @staticmethod
    def _topic(row: LogicTopic) -> LogicTopicRecord:
        return LogicTopicRecord(
            topic_id=row.topic_id,
            security_id=row.security_id,
            name=row.name,
            normalized_statement=row.normalized_statement,
            direction=row.direction,
            horizon=row.horizon,
            status=row.status,
            topic_version=row.topic_version,
            source_thesis_ids=list(row.source_thesis_ids or []),
            metadata=dict(row.metadata_json or {}),
            created_at=row.created_at,
        )

    @staticmethod
    def _relation(row: LogicTopicRelation) -> LogicTopicRelationRecord:
        return LogicTopicRelationRecord(
            relation_id=row.relation_id,
            topic_id=row.topic_id,
            object_type=row.object_type,
            object_id=row.object_id,
            relation=row.relation,
            confidence=row.confidence,
            source=row.source,
            reason=row.reason,
            citation_locators=list(row.citation_locators or []),
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            model_version=row.model_version,
            prompt_version=row.prompt_version,
            status=row.status,
            created_at=row.created_at,
        )

    def upsert_topics(self, records: list[LogicTopicRecord]) -> None:
        if not records:
            return
        statement = insert(LogicTopic).values(
            [
                {
                    "topic_id": row.topic_id,
                    "security_id": row.security_id,
                    "name": row.name,
                    "normalized_statement": row.normalized_statement,
                    "direction": row.direction,
                    "horizon": row.horizon,
                    "status": row.status,
                    "topic_version": row.topic_version,
                    "source_thesis_ids": row.source_thesis_ids,
                    "metadata_json": row.metadata,
                }
                for row in records
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=("topic_id",),
            set_={
                "name": statement.excluded.name,
                "normalized_statement": statement.excluded.normalized_statement,
                "status": statement.excluded.status,
                "source_thesis_ids": statement.excluded.source_thesis_ids,
                "metadata": statement.excluded.metadata,
            },
        )
        self._session.execute(statement)
        self._session.flush()

    def upsert_topic_relations(self, records: list[LogicTopicRelationRecord]) -> None:
        if not records:
            return
        statement = insert(LogicTopicRelation).values(
            [
                {
                    "relation_id": row.relation_id,
                    "topic_id": row.topic_id,
                    "object_type": row.object_type,
                    "object_id": row.object_id,
                    "relation": row.relation,
                    "confidence": row.confidence,
                    "source": row.source,
                    "reason": row.reason,
                    "citation_locators": row.citation_locators,
                    "valid_from": row.valid_from,
                    "valid_to": row.valid_to,
                    "model_version": row.model_version,
                    "prompt_version": row.prompt_version,
                    "status": row.status,
                }
                for row in records
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=("relation_id",),
            set_={
                "confidence": statement.excluded.confidence,
                "reason": statement.excluded.reason,
                "citation_locators": statement.excluded.citation_locators,
                "valid_from": statement.excluded.valid_from,
                "valid_to": statement.excluded.valid_to,
                "status": statement.excluded.status,
            },
        )
        self._session.execute(statement)
        self._session.flush()

    def topics(self, *, security_id: str, direction: str, horizon: str):
        rows = self._session.scalars(
            select(LogicTopic)
            .where(
                LogicTopic.security_id == security_id,
                LogicTopic.direction == direction,
                LogicTopic.horizon == horizon,
                LogicTopic.status == "active",
            )
            .order_by(LogicTopic.topic_id)
        ).all()
        return [self._topic(row) for row in rows]

    def topic_relations(self, topic_id: str):
        rows = self._session.scalars(
            select(LogicTopicRelation)
            .where(LogicTopicRelation.topic_id == topic_id, LogicTopicRelation.status == "active")
            .order_by(LogicTopicRelation.object_type, LogicTopicRelation.object_id)
        ).all()
        return [self._relation(row) for row in rows]

    def add_snapshot(self, record: RankingPriorSnapshotRecord) -> None:
        self._session.add(
            RankingPriorSnapshot(
                snapshot_id=record.snapshot_id,
                security_id=record.security_id,
                direction=record.direction,
                horizon=record.horizon,
                as_of=record.as_of,
                ranker_version=record.ranker_version,
                feature_version=record.feature_version,
                generator_model_version=record.generator_model_version,
                judge_model_version=record.judge_model_version,
                prompt_version=record.prompt_version,
                status=record.status,
                metadata_json=record.metadata,
            )
        )
        self._session.flush()

    def get_snapshot(self, snapshot_id: str) -> RankingPriorSnapshotRecord | None:
        row = self._session.get(RankingPriorSnapshot, snapshot_id)
        return self._snapshot(row) if row else None

    def update_snapshot_status(self, snapshot_id: str, status: str) -> None:
        self._session.execute(
            update(RankingPriorSnapshot)
            .where(RankingPriorSnapshot.snapshot_id == snapshot_id)
            .values(status=status)
        )
        self._session.flush()

    def active_snapshot(self, *, security_id, direction, horizon, as_of):
        statement = (
            select(RankingPriorSnapshot)
            .where(
                RankingPriorSnapshot.security_id == security_id,
                RankingPriorSnapshot.direction == direction,
                RankingPriorSnapshot.horizon == horizon,
                RankingPriorSnapshot.status.in_(("provisional", "active", "active_experimental")),
            )
            .order_by(RankingPriorSnapshot.as_of.desc(), RankingPriorSnapshot.created_at.desc())
            .limit(1)
        )
        if as_of is not None:
            statement = statement.where(RankingPriorSnapshot.as_of <= as_of)
        row = self._session.scalar(statement)
        return self._snapshot(row) if row else None

    def add_items(self, records: list[RankingPriorItemRecord]) -> None:
        if not records:
            return
        statement = insert(RankingPriorItem).values(
            [
                {
                    "snapshot_id": row.snapshot_id,
                    "object_type": row.object_type,
                    "object_id": row.object_id,
                    "base_rank": row.base_rank,
                    "base_score": row.base_score,
                    "judge_rank": row.judge_rank,
                    "judge_score": row.judge_score,
                    "judge_confidence": row.judge_confidence,
                    "final_rank": row.final_rank,
                    "final_score": row.final_score,
                    "feature_scores": row.feature_scores,
                    "reason_codes": row.reason_codes,
                    "citation_locators": row.citation_locators,
                    "status": row.status,
                }
                for row in records
            ]
        )
        statement = statement.on_conflict_do_update(
            index_elements=("snapshot_id", "object_type", "object_id"),
            set_={
                "base_rank": statement.excluded.base_rank,
                "base_score": statement.excluded.base_score,
                "judge_rank": statement.excluded.judge_rank,
                "judge_score": statement.excluded.judge_score,
                "judge_confidence": statement.excluded.judge_confidence,
                "final_rank": statement.excluded.final_rank,
                "final_score": statement.excluded.final_score,
                "feature_scores": statement.excluded.feature_scores,
                "reason_codes": statement.excluded.reason_codes,
                "citation_locators": statement.excluded.citation_locators,
                "status": statement.excluded.status,
            },
        )
        self._session.execute(statement)
        self._session.flush()

    def items_for_objects(self, snapshot_id, *, object_type, object_ids):
        if not object_ids:
            return []
        rows = self._session.scalars(
            select(RankingPriorItem).where(
                RankingPriorItem.snapshot_id == snapshot_id,
                RankingPriorItem.object_type == object_type,
                RankingPriorItem.object_id.in_(object_ids),
                RankingPriorItem.status == "active",
            )
        ).all()
        return [self._item(row) for row in rows]

    def ranked_items(self, snapshot_id, *, object_type, limit):
        rows = self._session.scalars(
            select(RankingPriorItem)
            .where(
                RankingPriorItem.snapshot_id == snapshot_id,
                RankingPriorItem.object_type == object_type,
                RankingPriorItem.status == "active",
            )
            .order_by(RankingPriorItem.final_rank)
            .limit(limit)
        ).all()
        return [self._item(row) for row in rows]
