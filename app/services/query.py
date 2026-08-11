"""只读查询编排。

前端的列表、趋势、待办、留痕四类读接口都走这里。与 `thesis.py`/`status.py` 分开是
因为职责不同：那两个模块改状态、写审计、过人工闸门，这里一行都不写。

三条约束：

1. **可见性过滤在服务层做，不在仓储做。** 仓储只管存取，权限是业务规则
   （`app/db/repositories/thesis.py` 的模块文档写明了这条）。
2. **列表强制分页且有上限。** 契约禁止无上限查询（对齐 PRD 12.2 列表 P95 <= 2 秒）。
   上限在这里兜住，因为 API 不是唯一入口。
3. **趋势不重新算数。** 直接调 `app/calc/deterministic.trend`，口径与失效判定用的
   是同一套计算，否则页面上的趋势和状态建议会互相矛盾。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.calc.deterministic import Observation, TrendResult, trend
from app.core.config import RuleThresholds
from app.core.domain import (
    AuditRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ThesisQuery,
    ThesisRecord,
    UnitOfWork,
)
from app.core.enums import ConfirmationStatus
from app.services.permission import Actor, can_view_thesis

# 单页上限。前端分页器默认 20，给到 100 已足够；再大就该走导出而不是列表接口。
MAX_LIMIT = 100


@dataclass(frozen=True)
class Page:
    """分页结果。

    `total` 是过滤后的总数。可见性过滤发生在取回当页之后，所以这个数字是
    「候选总数」而不是「你能看到的总数」——见 list_theses 的说明。
    """

    items: list[ThesisRecord]
    total: int
    limit: int
    offset: int


def clamp_limit(limit: int) -> int:
    """把 limit 夹到 [1, MAX_LIMIT]。

    0 或负数当成 1 而不是报错：前端传 0 通常是未初始化，返回一条比返回 400 友好，
    也比返回全表安全。
    """
    if limit < 1:
        return 1
    return min(limit, MAX_LIMIT)


def list_theses(uow: UnitOfWork, actor: Actor, query: ThesisQuery) -> Page:
    """分页列出当前用户可见的卡片。

    可见性过滤在取回当页之后做，因此当页条数可能少于 limit。这是有意的取舍：
    要让 total 精确等于「可见条数」，就得把全部候选取回内存再过滤，分页也就白做了。
    前端据 total 渲染页码，据 items 渲染行——少几行不影响翻页，把库拖垮才影响。
    """
    records, total = uow.thesis.search(
        ThesisQuery(
            statuses=query.statuses,
            securities=query.securities,
            owner=query.owner,
            keyword=query.keyword,
            limit=clamp_limit(query.limit),
            offset=max(query.offset, 0),
        )
    )
    visible = [
        r
        for r in records
        if can_view_thesis(
            actor,
            owner=r.owner,
            visibility=r.visibility,
            team=r.team,
        )
    ]
    return Page(
        items=visible, total=total, limit=clamp_limit(query.limit), offset=max(query.offset, 0)
    )


@dataclass(frozen=True)
class HypothesisTrend:
    """一条假设的趋势视图。

    口径字段（`period_type`/`unit`/`metric_version`/`data_version`）必须带上：
    FR-V-001 要求展示口径、报告期与来源，只给一串数字前端满足不了这条。
    """

    hypothesis_id: str
    statement: str
    metric_id: str
    unit: str
    period_type: str
    metric_version: str
    data_version: str | None
    result: TrendResult | None
    note: str = ""


def hypothesis_trends(
    uow: UnitOfWork,
    thesis: ThesisRecord,
    *,
    thresholds: RuleThresholds | None = None,
) -> list[HypothesisTrend]:
    """按假设组装趋势。

    没有指标映射的假设也返回一行，`result` 为 None 并写明原因——H3 产能与扩张
    本来就没有量化指标（见 analytics/pipelines/build_theses.py 的说明）。
    静默跳过会让前端以为这条假设不存在。

    观察窗口按 thesis 建立日裁剪：早于建立日的观测不参与，否则会把逻辑成立之前的
    历史算成对它的验证（`app/calc/rules.py` 模块文档里的同一条约束）。
    """
    conf = thresholds or RuleThresholds()
    trends: list[HypothesisTrend] = []

    for hypothesis in uow.thesis.list_hypotheses(thesis.thesis_id):
        mappings = uow.thesis.list_mappings(hypothesis.hypothesis_id)
        if not mappings:
            trends.append(
                HypothesisTrend(
                    hypothesis_id=hypothesis.hypothesis_id,
                    statement=hypothesis.statement,
                    metric_id="",
                    unit="",
                    period_type="",
                    metric_version="",
                    data_version=None,
                    result=None,
                    note="该假设无量化指标映射，只能人工判断",
                )
            )
            continue
        trends.append(_trend_for(uow, thesis, hypothesis, mappings[0], conf))

    return trends


def _trend_for(
    uow: UnitOfWork,
    thesis: ThesisRecord,
    hypothesis: HypothesisRecord,
    mapping: MetricMappingRecord,
    conf: RuleThresholds,
) -> HypothesisTrend:
    rows = uow.observations.list_for_metric(thesis.security_id, mapping.metric_id)
    # 窗口裁剪：早于建立日可得的观测不算对这条逻辑的验证。
    in_window = [r for r in rows if r.observation_date >= thesis.established_on]

    observations = [
        Observation(
            metric_id=r.metric_id,
            period=r.period,
            period_type=r.period_type,
            unit=r.unit,
            observation_date=r.observation_date,
            actual_value=r.actual_value,
            expected_value=r.expected_value
            if r.expected_value is not None
            else mapping.expected_value,
            metric_version=r.metric_version,
        )
        for r in in_window
    ]

    result = (
        trend(
            observations,
            min_periods=conf.trend_min_periods,
            max_periods=conf.trend_max_periods,
            direction=mapping.expected_direction,
        )
        if observations
        else None
    )

    latest = max(in_window, key=lambda r: r.observation_date, default=None)
    excluded = len(rows) - len(in_window)
    return HypothesisTrend(
        hypothesis_id=hypothesis.hypothesis_id,
        statement=hypothesis.statement,
        metric_id=mapping.metric_id,
        unit=latest.unit if latest else "",
        period_type=latest.period_type if latest else "单季度",
        metric_version=mapping.metric_version,
        data_version=latest.data_version if latest else None,
        result=result,
        note=(f"已排除逻辑建立日之前的 {excluded} 期观测" if excluded else ""),
    )


@dataclass(frozen=True)
class PendingItem:
    """一条待办。`kind` 决定前端跳到哪个处置入口。"""

    kind: str
    thesis_id: str
    title: str
    object_id: str
    summary: str
    occurred_on: date | None = None


@dataclass(frozen=True)
class Workbench:
    """工作台聚合视图（PRD 6.1 一级导航之一）。

    只统计当前用户可见的卡片。`status_counts` 用于顶部概览，两个待办列表用于
    「今天该处理什么」。
    """

    status_counts: dict[str, int] = field(default_factory=dict)
    pending_evidence: list[PendingItem] = field(default_factory=list)
    pending_suggestions: list[PendingItem] = field(default_factory=list)
    review_due: list[PendingItem] = field(default_factory=list)


def workbench(
    uow: UnitOfWork,
    actor: Actor,
    *,
    today: date | None = None,
    limit: int = 20,
) -> Workbench:
    """组装工作台。

    待办只取可见卡片下的条目。逐卡查询在 MVP 的数据量下可接受；卡片数量上千时
    应改为一次聚合查询，那时再改，不要现在就为想象的规模写复杂代码。
    """
    now = today or date.today()
    capped = clamp_limit(limit)

    visible, _ = uow.thesis.search(ThesisQuery(limit=MAX_LIMIT))
    mine = [
        r
        for r in visible
        if can_view_thesis(actor, owner=r.owner, visibility=r.visibility, team=r.team)
    ]

    counts: dict[str, int] = {}
    for record in mine:
        counts[record.status.value] = counts.get(record.status.value, 0) + 1

    evidence_items: list[PendingItem] = []
    suggestion_items: list[PendingItem] = []
    review_items: list[PendingItem] = []

    for record in mine:
        for ev in uow.evidence.list_for_thesis(record.thesis_id):
            if ev.confirmation_status is ConfirmationStatus.PENDING:
                evidence_items.append(
                    PendingItem(
                        kind="证据待确认",
                        thesis_id=record.thesis_id,
                        title=record.title,
                        object_id=ev.evidence_id,
                        summary=f"{ev.hypothesis_id} {ev.direction.value}",
                    )
                )
        for sug in uow.suggestions.list_for_thesis(record.thesis_id):
            if sug.human_action is None:
                suggestion_items.append(
                    PendingItem(
                        kind="状态建议待处置",
                        thesis_id=record.thesis_id,
                        title=record.title,
                        object_id=str(sug.suggestion_id or ""),
                        summary=f"{sug.current_status.value} → {sug.suggested_status.value}",
                    )
                )
        if record.next_review_at is not None and record.next_review_at <= now:
            review_items.append(
                PendingItem(
                    kind="复核到期",
                    thesis_id=record.thesis_id,
                    title=record.title,
                    object_id=record.thesis_id,
                    summary=f"复核日 {record.next_review_at.isoformat()}",
                    occurred_on=record.next_review_at,
                )
            )

    return Workbench(
        status_counts=counts,
        pending_evidence=evidence_items[:capped],
        pending_suggestions=suggestion_items[:capped],
        review_due=review_items[:capped],
    )


def audit_trail(
    uow: UnitOfWork,
    *,
    object_type: str,
    object_id: str,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AuditRecord], int]:
    """留痕分页。调用方负责先校验对象可见性。"""
    return uow.audit.page_for_object(
        object_type, object_id, limit=clamp_limit(limit), offset=max(offset, 0)
    )
