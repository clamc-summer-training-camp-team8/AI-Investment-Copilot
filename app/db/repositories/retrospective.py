"""SQL repositories for governed retrospective reports."""

from __future__ import annotations

from sqlalchemy import Text, and_, cast, false, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.domain import (
    RetrospectiveQuery,
    RetrospectiveRecord,
    RetrospectiveSourceRecord,
    RetrospectiveVersionRecord,
)
from app.db.models.core import Hypothesis, Security, Thesis
from app.db.models.governance import Retrospective, RetrospectiveSource, RetrospectiveVersion


def _record(row: Retrospective) -> RetrospectiveRecord:
    return RetrospectiveRecord(
        retrospective_id=row.retrospective_id,
        thesis_id=row.thesis_id,
        retrospective_type=row.retrospective_type,
        title=row.title,
        period_start=row.period_start,
        period_end=row.period_end,
        data_cutoff_at=row.data_cutoff_at,
        owner=row.owner,
        reviewer=row.reviewer,
        visibility=row.visibility,
        team=row.team,
        state=row.state,
        source_fingerprint=row.source_fingerprint,
        source_count=row.source_count,
        completeness_completed=row.completeness_completed,
        completeness_applicable=row.completeness_applicable,
        completeness_score=row.completeness_score,
        draft_content=dict(row.draft_content or {}),
        ai_candidate=dict(row.ai_candidate) if row.ai_candidate else None,
        ai_run_id=row.ai_run_id,
        ai_model_version=row.ai_model_version,
        ai_prompt_version=row.ai_prompt_version,
        ai_schema_version=row.ai_schema_version,
        current_version=row.current_version,
        lock_version=row.lock_version,
        submitted_at=row.submitted_at,
        published_at=row.published_at,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _source(row: RetrospectiveSource) -> RetrospectiveSourceRecord:
    return RetrospectiveSourceRecord(
        source_id=row.source_id,
        retrospective_id=row.retrospective_id,
        source_type=row.source_type,
        object_id=row.object_id,
        object_version=row.object_version,
        locator=row.locator,
        content_hash=row.content_hash,
        summary=row.summary,
        direction=row.direction,
        strength=row.strength,
        hypothesis_id=row.hypothesis_id,
        disclosed_at=row.disclosed_at,
        confirmed_at=row.confirmed_at,
        visibility_label=row.visibility_label,
        metadata=dict(row.source_metadata or {}),
        created_at=row.created_at,
    )


def _version(row: RetrospectiveVersion) -> RetrospectiveVersionRecord:
    return RetrospectiveVersionRecord(
        retrospective_id=row.retrospective_id,
        version=row.version,
        content=dict(row.content or {}),
        source_fingerprint=row.source_fingerprint,
        published_by=row.published_by,
        publish_reason=row.publish_reason,
        ai_run_id=row.ai_run_id,
        model_version=row.model_version,
        prompt_version=row.prompt_version,
        schema_version=row.schema_version,
        created_at=row.created_at,
    )


class SqlRetrospectiveRepo:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, record: RetrospectiveRecord) -> RetrospectiveRecord:
        row = Retrospective(
            retrospective_id=record.retrospective_id,
            thesis_id=record.thesis_id,
            retrospective_type=record.retrospective_type,
            title=record.title,
            period_start=record.period_start,
            period_end=record.period_end,
            data_cutoff_at=record.data_cutoff_at,
            owner=record.owner,
            reviewer=record.reviewer,
            visibility=record.visibility,
            team=record.team,
            state=record.state,
            source_fingerprint=record.source_fingerprint,
            source_count=record.source_count,
            completeness_completed=record.completeness_completed,
            completeness_applicable=record.completeness_applicable,
            completeness_score=record.completeness_score,
            draft_content=record.draft_content,
            ai_candidate=record.ai_candidate,
            ai_run_id=record.ai_run_id,
            ai_model_version=record.ai_model_version,
            ai_prompt_version=record.ai_prompt_version,
            ai_schema_version=record.ai_schema_version,
            current_version=record.current_version,
            lock_version=record.lock_version,
            submitted_at=record.submitted_at,
            published_at=record.published_at,
            archived_at=record.archived_at,
        )
        self._session.add(row)
        try:
            self._session.flush()
        except IntegrityError as exc:
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if constraint == "uq_retrospective_scope":
                raise RuntimeError("retrospective_scope_conflict") from exc
            raise
        return _record(row)

    def get(self, retrospective_id: str) -> RetrospectiveRecord | None:
        row = self._session.get(Retrospective, retrospective_id)
        return None if row is None else _record(row)

    def update(self, record: RetrospectiveRecord, *, expected_lock_version: int) -> None:
        result = self._session.execute(
            update(Retrospective)
            .where(
                Retrospective.retrospective_id == record.retrospective_id,
                Retrospective.lock_version == expected_lock_version,
            )
            .values(
                title=record.title,
                reviewer=record.reviewer,
                state=record.state,
                source_fingerprint=record.source_fingerprint,
                source_count=record.source_count,
                completeness_completed=record.completeness_completed,
                completeness_applicable=record.completeness_applicable,
                completeness_score=record.completeness_score,
                draft_content=record.draft_content,
                ai_candidate=record.ai_candidate,
                ai_run_id=record.ai_run_id,
                ai_model_version=record.ai_model_version,
                ai_prompt_version=record.ai_prompt_version,
                ai_schema_version=record.ai_schema_version,
                current_version=record.current_version,
                lock_version=record.lock_version,
                submitted_at=record.submitted_at,
                published_at=record.published_at,
                archived_at=record.archived_at,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            raise RuntimeError("retrospective_lock_conflict")
        self._session.flush()

    def find_active(
        self,
        *,
        thesis_id: str,
        retrospective_type: str,
        period_start,
        period_end,
    ) -> RetrospectiveRecord | None:
        row = self._session.scalar(
            select(Retrospective).where(
                Retrospective.thesis_id == thesis_id,
                Retrospective.retrospective_type == retrospective_type,
                Retrospective.period_start == period_start,
                Retrospective.period_end == period_end,
                Retrospective.state != "已归档",
            )
        )
        return None if row is None else _record(row)

    def search_visible(
        self,
        *,
        actor_id: str,
        teams: tuple[str, ...],
        query: RetrospectiveQuery,
    ) -> tuple[list[RetrospectiveRecord], int]:
        team_condition = (
            and_(Retrospective.visibility == "团队", Retrospective.team.in_(teams))
            if teams
            else false()
        )
        published_visible = and_(
            Retrospective.state.in_(("已发布", "已归档")),
            or_(Retrospective.owner == actor_id, team_condition),
        )
        visible = or_(
            Retrospective.owner == actor_id,
            Retrospective.reviewer == actor_id,
            published_visible,
        )
        conditions = [visible]
        if query.state:
            conditions.append(Retrospective.state == query.state)
        if query.retrospective_type:
            conditions.append(Retrospective.retrospective_type == query.retrospective_type)
        if query.owner:
            conditions.append(Retrospective.owner == query.owner)
        if query.reviewer:
            conditions.append(Retrospective.reviewer == query.reviewer)
        if query.security_id:
            conditions.append(Security.security_id == query.security_id)
        if query.industry:
            conditions.append(Security.industry == query.industry)
        if query.completeness_min is not None:
            conditions.append(Retrospective.completeness_score >= query.completeness_min)
        if query.completeness_max is not None:
            conditions.append(Retrospective.completeness_score <= query.completeness_max)
        if query.period_start:
            conditions.append(Retrospective.period_end >= query.period_start)
        if query.period_end:
            conditions.append(Retrospective.period_start <= query.period_end)
        if query.published_start:
            conditions.append(func.date(Retrospective.published_at) >= query.published_start)
        if query.published_end:
            conditions.append(func.date(Retrospective.published_at) <= query.published_end)
        if query.has_strong_conflict is not None:
            strong_conflict = select(RetrospectiveSource.source_id).where(
                RetrospectiveSource.retrospective_id == Retrospective.retrospective_id,
                RetrospectiveSource.source_type == "confirmed_evidence",
                RetrospectiveSource.direction == "冲突",
                RetrospectiveSource.strength == "高",
            )
            conditions.append(
                strong_conflict.exists() if query.has_strong_conflict else ~strong_conflict.exists()
            )
        if query.hypothesis_result:
            result_pattern = f'%"result": "{query.hypothesis_result}"%'
            version_result = select(RetrospectiveVersion.id).where(
                RetrospectiveVersion.retrospective_id == Retrospective.retrospective_id,
                cast(RetrospectiveVersion.content, Text).ilike(result_pattern),
            )
            can_view_draft = or_(
                Retrospective.owner == actor_id,
                Retrospective.reviewer == actor_id,
            )
            conditions.append(
                or_(
                    and_(
                        can_view_draft,
                        cast(Retrospective.draft_content, Text).ilike(result_pattern),
                    ),
                    version_result.exists(),
                )
            )
        if query.query:
            escaped = query.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            can_view_draft = or_(
                Retrospective.owner == actor_id,
                Retrospective.reviewer == actor_id,
            )
            conditions.append(
                Retrospective.title.ilike(pattern, escape="\\")
                | Thesis.title.ilike(pattern, escape="\\")
                | Thesis.core_view.ilike(pattern, escape="\\")
                | Security.name.ilike(pattern, escape="\\")
                | Security.security_id.ilike(pattern, escape="\\")
                | select(Hypothesis.hypothesis_id)
                .where(
                    Hypothesis.thesis_id == Thesis.thesis_id,
                    Hypothesis.statement.ilike(pattern, escape="\\"),
                )
                .exists()
                | and_(
                    can_view_draft,
                    cast(Retrospective.draft_content, Text).ilike(pattern, escape="\\"),
                )
                | select(RetrospectiveVersion.id)
                .where(
                    RetrospectiveVersion.retrospective_id == Retrospective.retrospective_id,
                    cast(RetrospectiveVersion.content, Text).ilike(pattern, escape="\\"),
                )
                .exists()
            )

        base = (
            select(Retrospective)
            .join(Thesis, Thesis.thesis_id == Retrospective.thesis_id)
            .join(Security, Security.security_id == Thesis.security_id)
            .where(*conditions)
        )
        total = self._session.scalar(select(func.count()).select_from(base.subquery())) or 0
        sort_columns = {
            "updated_at": Retrospective.updated_at,
            "published_at": Retrospective.published_at,
            "period_end": Retrospective.period_end,
            "completeness_score": Retrospective.completeness_score,
        }
        sort_column = sort_columns.get(query.sort, Retrospective.updated_at)
        ordering = sort_column.asc() if query.direction == "asc" else sort_column.desc()
        rows = self._session.scalars(
            base.order_by(ordering, Retrospective.retrospective_id)
            .limit(query.limit)
            .offset(query.offset)
        ).all()
        return [_record(row) for row in rows], int(total)

    def add_sources(self, records: list[RetrospectiveSourceRecord]) -> None:
        self._session.add_all(
            [
                RetrospectiveSource(
                    source_id=item.source_id,
                    retrospective_id=item.retrospective_id,
                    source_type=item.source_type,
                    object_id=item.object_id,
                    object_version=item.object_version,
                    locator=item.locator,
                    content_hash=item.content_hash,
                    summary=item.summary,
                    direction=item.direction,
                    strength=item.strength,
                    hypothesis_id=item.hypothesis_id,
                    disclosed_at=item.disclosed_at,
                    confirmed_at=item.confirmed_at,
                    visibility_label=item.visibility_label,
                    source_metadata=item.metadata,
                )
                for item in records
            ]
        )
        self._session.flush()

    def list_sources(self, retrospective_id: str) -> list[RetrospectiveSourceRecord]:
        rows = self._session.scalars(
            select(RetrospectiveSource)
            .where(RetrospectiveSource.retrospective_id == retrospective_id)
            .order_by(
                RetrospectiveSource.disclosed_at,
                RetrospectiveSource.created_at,
                RetrospectiveSource.source_id,
            )
        ).all()
        return [_source(row) for row in rows]

    def add_version(self, record: RetrospectiveVersionRecord) -> None:
        self._session.add(
            RetrospectiveVersion(
                retrospective_id=record.retrospective_id,
                version=record.version,
                content=record.content,
                source_fingerprint=record.source_fingerprint,
                published_by=record.published_by,
                publish_reason=record.publish_reason,
                ai_run_id=record.ai_run_id,
                model_version=record.model_version,
                prompt_version=record.prompt_version,
                schema_version=record.schema_version,
            )
        )
        self._session.flush()

    def get_version(self, retrospective_id: str, version: int) -> RetrospectiveVersionRecord | None:
        row = self._session.scalar(
            select(RetrospectiveVersion).where(
                RetrospectiveVersion.retrospective_id == retrospective_id,
                RetrospectiveVersion.version == version,
            )
        )
        return None if row is None else _version(row)

    def list_versions(self, retrospective_id: str) -> list[RetrospectiveVersionRecord]:
        rows = self._session.scalars(
            select(RetrospectiveVersion)
            .where(RetrospectiveVersion.retrospective_id == retrospective_id)
            .order_by(RetrospectiveVersion.version.desc())
        ).all()
        return [_version(row) for row in rows]
