"""逻辑、假设、映射仓储。

只做数据存取。不做权限过滤（权限是业务规则，属于 app/services），不写审计。
枚举与 Decimal 在这里完成 ORM 与服务层值对象之间的转换——服务层不 import
app.db.models，避免编排逻辑与表结构耦合。
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.core.domain import (
    HypothesisRecord,
    MetricMappingRecord,
    ThesisQuery,
    ThesisRecord,
)
from app.core.enums import ConfirmationStatus, ExpectationDirection, Importance, ThesisStatus
from app.db.models.core import Hypothesis, HypothesisMetricMap, Thesis


def _to_thesis(row: Thesis, *, participating: list[str] | None = None) -> ThesisRecord:
    return ThesisRecord(
        thesis_id=row.thesis_id,
        security_id=row.security_id,
        title=row.title,
        direction=row.direction,
        core_view=row.core_view,
        established_on=row.established_on,
        owner=row.owner,
        status=ThesisStatus(row.status),
        visibility=row.visibility,
        team=row.team,
        version=row.version,
        horizon_end_on=row.horizon_end_on,
        next_review_at=row.next_review_at,
        source_document_id=row.source_document_id,
        is_illustrative=row.is_illustrative,
        invalidation_require_all=row.invalidation_require_all,
        invalidation_hypotheses=participating or [],
    )


class SqlThesisRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, thesis_id: str) -> ThesisRecord | None:
        row = self._session.get(Thesis, thesis_id)
        if row is None:
            return None
        return _to_thesis(row, participating=self._participating(thesis_id))

    def add(self, record: ThesisRecord) -> None:
        self._session.add(
            Thesis(
                thesis_id=record.thesis_id,
                security_id=record.security_id,
                title=record.title,
                direction=record.direction,
                core_view=record.core_view,
                established_on=record.established_on,
                horizon_end_on=record.horizon_end_on,
                next_review_at=record.next_review_at,
                owner=record.owner,
                visibility=record.visibility,
                team=record.team,
                status=record.status.value,
                invalidation_require_all=record.invalidation_require_all,
                version=record.version,
                source_document_id=record.source_document_id,
                is_illustrative=record.is_illustrative,
            )
        )
        self._session.flush()

    def update(self, record: ThesisRecord) -> None:
        row = self._session.get(Thesis, record.thesis_id)
        if row is None:
            raise LookupError(f"thesis {record.thesis_id} 不存在")
        row.title = record.title
        row.direction = record.direction
        row.core_view = record.core_view
        row.status = record.status.value
        row.visibility = record.visibility
        row.team = record.team
        row.invalidation_require_all = record.invalidation_require_all
        row.version = record.version
        row.horizon_end_on = record.horizon_end_on
        row.next_review_at = record.next_review_at
        self._session.flush()

    def list_hypotheses(self, thesis_id: str) -> list[HypothesisRecord]:
        rows = self._session.scalars(
            select(Hypothesis)
            .where(Hypothesis.thesis_id == thesis_id)
            .order_by(Hypothesis.hypothesis_id)
        ).all()
        return [
            HypothesisRecord(
                hypothesis_id=r.hypothesis_id,
                thesis_id=r.thesis_id,
                statement=r.statement,
                hypothesis_type=r.hypothesis_type,
                importance=Importance(r.importance),
                name=r.name,
                weight=r.weight,
                observation_window=r.observation_window,
                expected_direction=(
                    ExpectationDirection(r.expected_direction) if r.expected_direction else None
                ),
                invalidation_rule=r.invalidation_rule,
                status=r.status,
            )
            for r in rows
        ]

    def add_hypothesis(self, record: HypothesisRecord) -> None:
        self._session.add(
            Hypothesis(
                hypothesis_id=record.hypothesis_id,
                thesis_id=record.thesis_id,
                statement=record.statement,
                hypothesis_type=record.hypothesis_type,
                importance=record.importance.value,
                name=record.name,
                weight=record.weight,
                observation_window=record.observation_window,
                expected_direction=(
                    record.expected_direction.value if record.expected_direction else None
                ),
                invalidation_rule=record.invalidation_rule,
                status=record.status,
            )
        )
        self._session.flush()

    def list_mappings(self, hypothesis_id: str) -> list[MetricMappingRecord]:
        rows = self._session.scalars(
            select(HypothesisMetricMap)
            .where(HypothesisMetricMap.hypothesis_id == hypothesis_id)
            .order_by(HypothesisMetricMap.mapping_id)
        ).all()
        return [
            MetricMappingRecord(
                mapping_id=r.mapping_id,
                hypothesis_id=r.hypothesis_id,
                metric_id=r.metric_id,
                expected_direction=ExpectationDirection(r.expected_direction),
                metric_version=r.metric_version,
                expected_value=r.expected_value,
                invalidation_threshold=r.invalidation_threshold,
                invalidation_consecutive_periods=_parse_periods(r.invalidation_rule),
                expectation_source=r.expectation_source,
                confirmation_status=ConfirmationStatus(r.confirmation_status),
            )
            for r in rows
        ]

    def add_mapping(self, record: MetricMappingRecord) -> None:
        self._session.add(
            HypothesisMetricMap(
                mapping_id=record.mapping_id,
                hypothesis_id=record.hypothesis_id,
                metric_id=record.metric_id,
                metric_version=record.metric_version,
                expected_direction=record.expected_direction.value,
                expected_value=record.expected_value,
                expectation_source=record.expectation_source,
                invalidation_threshold=record.invalidation_threshold,
                invalidation_rule=_format_periods(record.invalidation_consecutive_periods),
                confirmation_status=record.confirmation_status.value,
            )
        )
        self._session.flush()

    def find_by_security(self, security_id: str) -> list[ThesisRecord]:
        rows = self._session.scalars(
            select(Thesis).where(Thesis.security_id == security_id).order_by(Thesis.thesis_id)
        ).all()
        participating = self._participating_bulk([r.thesis_id for r in rows])
        return [_to_thesis(r, participating=participating.get(r.thesis_id, [])) for r in rows]

    def search(self, query: ThesisQuery) -> tuple[list[ThesisRecord], int]:
        """条件分页查询。

        总数用独立的 count 查询而不是 len(全量结果)：后者要把所有行拉进内存，
        分页就失去意义了。
        """
        conditions: list[ColumnElement[bool]] = []
        if query.statuses:
            conditions.append(Thesis.status.in_([s.value for s in query.statuses]))
        if query.securities:
            conditions.append(Thesis.security_id.in_(query.securities))
        if query.owner:
            conditions.append(Thesis.owner == query.owner)
        if query.keyword:
            # 标题与核心观点都匹配。ilike 的 % 需要转义，否则用户输入的 %
            # 会变成通配符，让「%」这类查询命中全表。
            pattern = "%{}%".format(
                query.keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            conditions.append(
                Thesis.title.ilike(pattern, escape="\\")
                | Thesis.core_view.ilike(pattern, escape="\\")
            )

        total = self._session.scalar(select(func.count()).select_from(Thesis).where(*conditions))

        rows = self._session.scalars(
            select(Thesis)
            .where(*conditions)
            # established_on 倒序让最新的卡片在前；thesis_id 兜底保证分页稳定，
            # 否则同一天建立的卡片在翻页时可能重复或漏掉。
            .order_by(Thesis.established_on.desc(), Thesis.thesis_id)
            .limit(query.limit)
            .offset(query.offset)
        ).all()

        participating = self._participating_bulk([r.thesis_id for r in rows])
        records = [_to_thesis(r, participating=participating.get(r.thesis_id, [])) for r in rows]
        return records, int(total or 0)

    def _participating(self, thesis_id: str) -> list[str]:
        """参与 thesis 级失效条件的假设：写了 invalidation_rule 的那些。

        没写失效条件的假设不该进 AND——它永远不突破，会永久压住失效判定。
        """
        return self._participating_bulk([thesis_id]).get(thesis_id, [])

    def _participating_bulk(self, thesis_ids: list[str]) -> dict[str, list[str]]:
        """批量版，避免列表接口逐条查假设表（N+1）。"""
        if not thesis_ids:
            return {}
        rows = self._session.execute(
            select(
                Hypothesis.thesis_id, Hypothesis.hypothesis_id, Hypothesis.invalidation_rule
            ).where(Hypothesis.thesis_id.in_(thesis_ids))
        ).all()
        result: dict[str, list[str]] = {}
        for thesis_id, hypothesis_id, rule in rows:
            if (rule or "").strip():
                result.setdefault(thesis_id, []).append(hypothesis_id)
        return result


def _parse_periods(rule: str | None) -> int | None:
    """从失效条件文本里读出连续期数。

    形如「[连续2期]海外收入低于预期」。取不到返回 None，由 calc 用全局默认值。
    """
    if not rule:
        return None
    matched = re.search(r"\[连续(\d+)期\]", rule)
    return int(matched.group(1)) if matched else None


def _format_periods(periods: int | None) -> str | None:
    return None if periods is None else f"[连续{periods}期]"
