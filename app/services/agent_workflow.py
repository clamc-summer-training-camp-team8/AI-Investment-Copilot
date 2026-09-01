"""Agent 能力与后端业务对象之间的应用编排。

本模块只生成并保存候选结果，不修改正式指标映射、证据确认状态或投资逻辑状态。
数据库查询、权限校验和候选持久化由服务层负责，``app.ai`` 保持无数据库依赖。
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

from app.ai.gateway import Gateway
from app.ai.integration import to_backend_envelope
from app.ai.retrieval import RetrievalDocument
from app.ai.runtime import InvestmentResearchAgent, RuntimeExecution
from app.ai.tools import MetricCatalogTool, ThresholdObservation
from app.core.config import Settings
from app.core.domain import ObservationRecord, ThesisRevisionDraftRecord, UnitOfWork
from app.core.enums import ConfirmationStatus, ThesisStatus
from app.core.timeutil import now
from app.services import assets, audit, permission, query, version
from app.services.ai_runtime import SqlRuntimeRecorder
from app.services.company_metrics import CompanyMetricObservation, fetch_periodic_metrics
from app.services.errors import HumanGateRequired, NotVisible, ValidationFailed
from app.services.permission import Actor


@dataclass(frozen=True)
class AgentCandidate:
    """供 Router 稳定返回的一次 Agent 候选执行。"""

    run_id: str
    task: str
    status: str
    ai_status: str | None
    requires_human_review: bool
    payload: dict[str, Any]
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RevisionCandidate:
    """AI 修订候选及其已有的版本化草稿。"""

    execution: AgentCandidate
    revision: ThesisRevisionDraftRecord


def build_runtime(settings: Settings) -> InvestmentResearchAgent:
    """构造生产 Runtime，并把运行轨迹写入现有 ``ai_run`` 表。"""

    return InvestmentResearchAgent.build(
        Gateway.build(settings),
        recorder=SqlRuntimeRecorder(),
    )


def build_database_metric_catalog(uow: UnitOfWork, security_id: str) -> MetricCatalogTool:
    """把当前证券的 PostgreSQL 指标投影为 Agent 可用的受控目录。

    ``app.ai`` 只接收目录快照，不依赖 ORM。推荐候选必须来自已经存在观测值的
    指标，避免把“指标字典里有定义”误报成“该证券已经有数据”。没有数据库观测时
    回退到版本化种子目录，以保持没有生产数据的单元测试和演示可运行。
    """
    security = uow.securities.get(security_id)
    definitions = uow.metrics.search(limit=500)
    if security is None or not definitions:
        return MetricCatalogTool.from_seed()

    metrics: list[dict[str, Any]] = []
    availability: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for definition in definitions:
        observations = uow.observations.list_for_metric(security.security_id, definition.metric_id)
        if not observations:
            continue
        category = definition.category or _infer_metric_category(definition.metric_id)
        source_id = definition.source_id or "postgresql-metric-observation"
        source_ids.add(source_id)
        metrics.append(
            {
                "metric_id": definition.metric_id,
                "version": definition.version,
                "name": definition.name,
                "definition": definition.definition or "数据库中已入库的证券指标。",
                "unit": definition.unit,
                "frequency": definition.frequency or "随数据源",
                "period_type": definition.period_type or "未标注",
                "expected_direction": _enum_value(definition.expected_direction),
                "industries": [security.industry or "通用"],
                "keywords": _database_metric_keywords(
                    metric_id=definition.metric_id,
                    name=definition.name,
                    definition=definition.definition,
                    category=category,
                ),
                "relation_type": "直接指标"
                if category in {"财务与运营", "经营", "盈利"}
                else "代理指标",
                "threshold_policy": "已有历史观测，可由研究员确认后设置区间；不自动写入正式规则",
            }
        )
        availability.append(
            {
                "metric_id": definition.metric_id,
                "security_id": security.security_id,
                "source_id": source_id,
                "availability_grade": "A",
                "observation_frequency": definition.frequency or "随数据源",
                "polling_frequency": "按数据源更新",
                "note": f"PostgreSQL 已有 {len(observations)} 条该证券观测。",
            }
        )

    if not metrics:
        return MetricCatalogTool.from_seed()

    sources = [
        {
            "source_id": source_id,
            "name": source_id,
            "source_type": "PostgreSQL 指标观测",
            "authorization_status": "已入库",
            "base_url": "",
            "note": "候选来自当前证券已入库观测，不代表数据源持续可用。",
        }
        for source_id in sorted(source_ids)
    ]
    content = {
        "catalog_version": "postgresql-metric-catalog-v1",
        "verified_on": now().date().isoformat(),
        "companies": [
            {
                "security_id": security.security_id,
                "name": security.name,
                "industry": security.industry or "通用",
                "role": "",
                "market": "",
            }
        ],
        "sources": sources,
        "metrics": metrics,
        "availability": availability,
    }
    return MetricCatalogTool.from_snapshot(content)


def _enum_value(value: Any) -> str | None:
    """兼容 ``StrEnum`` 与普通字符串，避免把枚举 repr 传给模型。"""
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _infer_metric_category(metric_id: str) -> str:
    prefix = metric_id.upper().split("-", 1)[0]
    return {
        "MKT": "价格与成交量",
        "TECH": "技术指标",
        "VAL": "估值指标",
        "FIN": "财务与运营",
        "INDUSTRY": "宏观及行业",
        "MACRO": "宏观及行业",
    }.get(prefix, "其他")


def _database_metric_keywords(
    *, metric_id: str, name: str, definition: str | None, category: str
) -> list[str]:
    """从数据库口径生成有限的业务短语，供候选召回而非自由编造指标。"""
    normalized_id = metric_id.upper()
    keywords: list[str] = [name.strip()] if len(name.strip()) >= 2 else []
    if normalized_id.startswith("FIN-REVENUE") or "营业收入" in name or "营收" in name:
        keywords.extend(("收入", "营收", "销售", "需求", "增长", "订单", "业绩", "市场份额"))
    elif normalized_id.startswith("FIN-NET-PROFIT") or "净利润" in name:
        keywords.extend(("利润", "盈利", "业绩", "增长", "改善", "收入"))
    elif normalized_id.startswith("FIN-GROSS-MARGIN") or "毛利率" in name:
        keywords.extend(("毛利率", "盈利", "利润", "改善", "成本", "价格", "产品结构"))
    elif normalized_id.startswith("FIN-ROE") or "净资产收益率" in name:
        keywords.extend(("净资产收益率", "盈利", "回报", "利润"))
    elif normalized_id.startswith("FIN-DEBT") or "资产负债率" in name:
        keywords.extend(("负债", "杠杆", "财务风险", "偿债"))
    elif normalized_id.startswith("FIN-OCF") or "现金流" in name:
        keywords.extend(("现金流", "回款", "经营", "资金压力", "经营质量"))
    elif normalized_id.startswith("VAL-") or category == "估值指标":
        keywords.extend(("估值", "股价", "市场表现", "价值", "盈利"))
    elif normalized_id.startswith("MKT-") or category == "价格与成交量":
        keywords.extend(("股价", "行情", "市场表现", "收益", "估值"))
    elif normalized_id.startswith("TECH-") or category == "技术指标":
        keywords.extend(("趋势", "波动", "股价", "行情", "市场表现"))
    elif normalized_id.startswith("INDUSTRY-"):
        keywords.extend(("行业", "市场", "需求", "增长", "景气"))
    elif normalized_id.startswith("MACRO-CPI"):
        keywords.extend(("消费", "价格", "通胀", "需求"))
    elif normalized_id.startswith("MACRO-PPI"):
        keywords.extend(("成本", "价格", "工业", "通胀"))
    elif normalized_id.startswith("MACRO-PMI"):
        keywords.extend(("制造业", "景气", "需求", "产能"))
    # 未登记的指标只保留指标全名，避免按单字或宽泛类别误召回。
    return list(dict.fromkeys(keywords))


def candidate_from_execution(execution: RuntimeExecution) -> AgentCandidate:
    """把 Runtime 内部对象收敛为不暴露实现细节的后端候选 DTO。"""

    envelope = to_backend_envelope(execution)
    result = envelope.get("candidate_result")
    result = dict(result) if isinstance(result, dict) else {}
    outcome = result.get("outcome")
    outcome = dict(outcome) if isinstance(outcome, dict) else {}
    raw_payload = outcome.get("payload") if outcome else result
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    ai_status = outcome.get("ai_status") or payload.get("ai_status")
    return AgentCandidate(
        run_id=execution.run_id,
        task=execution.task,
        status=execution.status,
        ai_status=str(ai_status) if ai_status else None,
        requires_human_review=bool(
            payload.get("requires_human_review", envelope.get("requires_human_review", True))
        ),
        payload=payload,
        errors=tuple(execution.errors),
    )


def enrich_draft_metric_suggestions(
    uow: UnitOfWork,
    *,
    draft: dict[str, Any],
    thesis_id: str,
    security_id: str,
    industry: str | None,
    actor: Actor,
    settings: Settings,
    runtime: InvestmentResearchAgent | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """为建卡结果中的每条假设补充受控指标和确定性阈值候选。

    单条指标推荐失败不会阻断逻辑草稿创建；失败信息写审计，原始 Thesis Draft
    建议仍保留。这样模型供应商局部失败不会让研究员丢失已经生成的草稿。
    """

    active_runtime = runtime or build_runtime(settings)
    if runtime is None:
        active_runtime.metric_research.catalog = build_database_metric_catalog(uow, security_id)
    enriched = deepcopy(draft)
    hypotheses = enriched.get("hypotheses")
    if not isinstance(hypotheses, list):
        return enriched
    cutoff = as_of or date.today()

    for index, hypothesis in enumerate(hypotheses, start=1):
        if not isinstance(hypothesis, dict):
            continue
        hypothesis_id = f"{thesis_id}-H{index}"
        statement = str(hypothesis.get("statement") or "").strip()
        if not statement:
            continue
        execution = active_runtime.recommend_metrics(
            security_id=security_id,
            hypothesis_id=hypothesis_id,
            hypothesis=statement,
            industry=industry,
            top_k=8,
            idempotency_key=f"draft:{thesis_id}:metric:{hypothesis_id}",
        )
        candidate = candidate_from_execution(execution)
        recommendations = candidate.payload.get("recommendations") if candidate.payload else None
        if not isinstance(recommendations, list):
            audit.record(
                uow.audit,
                actor=actor.user_id,
                action="指标候选生成失败",
                object_type="hypothesis",
                object_id=hypothesis_id,
                detail={"run_id": candidate.run_id, "errors": list(candidate.errors)},
            )
            continue
        hypothesis["metric_suggestions"] = [
            _recommendation_with_threshold(
                uow,
                runtime=active_runtime,
                security_id=security_id,
                recommendation=item,
                as_of=cutoff,
            )
            for item in recommendations
            if isinstance(item, dict)
        ]
        audit.record(
            uow.audit,
            actor=actor.user_id,
            action="生成指标与阈值候选",
            object_type="hypothesis",
            object_id=hypothesis_id,
            detail={
                "run_id": candidate.run_id,
                "catalog_version": candidate.payload.get("catalog_version"),
                "recommendation_count": len(hypothesis["metric_suggestions"]),
                "requires_human_review": True,
            },
            model_version=str(candidate.payload.get("model_version") or "") or None,
        )
    return enriched


def recommend_metrics(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    hypothesis_id: str,
    actor: Actor,
    settings: Settings,
    top_k: int = 8,
    as_of: date | None = None,
    runtime: InvestmentResearchAgent | None = None,
) -> AgentCandidate:
    """重新生成单条假设的指标候选；只更新候选区，不写正式映射。"""

    thesis, hypothesis = _visible_hypothesis(uow, thesis_id, hypothesis_id, actor)
    if thesis.owner != actor.user_id:
        raise HumanGateRequired("只有逻辑负责人可以生成指标候选")
    active_runtime = runtime or build_runtime(settings)
    security = uow.securities.get(thesis.security_id)
    if runtime is None:
        active_runtime.metric_research.catalog = build_database_metric_catalog(
            uow, thesis.security_id
        )
    execution = active_runtime.recommend_metrics(
        security_id=thesis.security_id,
        hypothesis_id=hypothesis.hypothesis_id,
        hypothesis=hypothesis.statement,
        industry=security.industry if security else None,
        top_k=top_k,
        idempotency_key=f"metric:{thesis_id}:{hypothesis_id}:{(as_of or date.today()).isoformat()}",
    )
    candidate = candidate_from_execution(execution)
    recommendations = candidate.payload.get("recommendations")
    if isinstance(recommendations, list):
        candidate.payload["recommendations"] = [
            _recommendation_with_threshold(
                uow,
                runtime=active_runtime,
                security_id=thesis.security_id,
                recommendation=item,
                as_of=as_of or date.today(),
            )
            for item in recommendations
            if isinstance(item, dict)
        ]
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="重新生成指标与阈值候选",
        object_type="hypothesis",
        object_id=hypothesis_id,
        detail={"run_id": candidate.run_id, "requires_human_review": True},
        model_version=str(candidate.payload.get("model_version") or "") or None,
    )
    return candidate


def explain_metric_results(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    hypothesis_id: str,
    actor: Actor,
    settings: Settings,
    runtime: InvestmentResearchAgent | None = None,
) -> AgentCandidate:
    """解释 ``app.calc`` 已经得到的趋势结果，不让模型重新计算指标。"""

    thesis, hypothesis = _visible_hypothesis(uow, thesis_id, hypothesis_id, actor)
    trend = next(
        (
            item
            for item in query.hypothesis_trends(uow, thesis, thresholds=settings.rules)
            if item.hypothesis_id == hypothesis_id
        ),
        None,
    )
    if trend is None:
        raise ValidationFailed("未找到该假设的指标计算结果")
    calc_result = _trend_calc_result(trend)
    execution = (runtime or build_runtime(settings)).explain_metric(
        security_id=thesis.security_id,
        hypothesis_id=hypothesis_id,
        hypothesis=hypothesis.statement,
        calc_result=calc_result,
        idempotency_key=f"metric-explain:{thesis_id}:{hypothesis_id}:{_calc_fingerprint(calc_result)}",
    )
    candidate = candidate_from_execution(execution)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="生成指标解释候选",
        object_type="hypothesis",
        object_id=hypothesis_id,
        detail={"run_id": candidate.run_id, "calculation_source": "app.calc"},
        model_version=str(candidate.payload.get("model_version") or "") or None,
    )
    return candidate


def draft_review(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    period_start: date,
    period_end: date,
    actor: Actor,
    settings: Settings,
    runtime: InvestmentResearchAgent | None = None,
    records_override: list[dict[str, Any]] | None = None,
) -> AgentCandidate:
    """从数据库中已确认且处于复盘区间内的记录生成复盘候选。"""

    if period_end < period_start:
        raise ValidationFailed("复盘结束日期不能早于开始日期")
    thesis = _visible_thesis(uow, thesis_id, actor)
    records = (
        records_override
        if records_override is not None
        else _review_records(uow, thesis_id, period_start, period_end)
    )
    execution = (runtime or build_runtime(settings)).draft_review(
        security_id=thesis.security_id,
        thesis_id=thesis_id,
        period_start=period_start,
        period_end=period_end,
        records=records,
        idempotency_key=f"review:{thesis_id}:{period_start.isoformat()}:{period_end.isoformat()}",
    )
    candidate = candidate_from_execution(execution)
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="生成复盘候选",
        object_type="thesis",
        object_id=thesis_id,
        detail={
            "run_id": candidate.run_id,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "record_count": len(records),
            "requires_human_review": True,
        },
        model_version=str(candidate.payload.get("model_version") or "") or None,
    )
    return candidate


def draft_revision(
    uow: UnitOfWork,
    *,
    thesis_id: str,
    actor: Actor,
    settings: Settings,
    runtime: InvestmentResearchAgent | None = None,
) -> RevisionCandidate:
    """在重大风险状态下基于最新可见资料生成版本化修订候选。"""

    thesis = _visible_thesis(uow, thesis_id, actor)
    if thesis.owner != actor.user_id:
        raise HumanGateRequired("只有逻辑负责人可以生成修订候选")
    if thesis.status is not ThesisStatus.MAJOR_RISK:
        raise ValidationFailed("只有已由人工确认进入重大风险的逻辑才能生成修订候选")
    if uow.assets.active_thesis_revision(thesis_id) is not None:
        raise ValidationFailed("已有编辑中的修订草稿，请先处理，避免覆盖人工修改")
    hypotheses = uow.thesis.list_hypotheses(thesis_id)
    search_text = " ".join([thesis.core_view, *(item.statement for item in hypotheses)])
    hits = assets.hybrid_retrieve(
        uow,
        query=search_text,
        actor=actor,
        settings=settings,
        security_ids=(thesis.security_id,),
        published_to=now(),
        limit=8,
    )
    source_documents = [
        RetrievalDocument(
            document_id=item.document_id,
            security_id=thesis.security_id,
            locator=item.locator,
            content=item.content,
            published_at=item.published_at,
            visibility_label=item.visibility_label,
            source=item.source,
        )
        for item in hits
        if item.published_at is not None
    ]
    active_runtime = runtime or build_runtime(settings)
    execution = active_runtime.draft_thesis(
        security_id=thesis.security_id,
        view="基于已确认的重大风险、冲突证据和最新资料，生成投资逻辑修订候选",
        source_segments=source_documents,
        investment_context={
            "thesis_id": thesis_id,
            "current_title": thesis.title,
            "current_core_view": thesis.core_view,
            "current_hypotheses": [asdict(item) for item in hypotheses],
            "confirmed_evidence": version.evidence_snapshot(uow, thesis_id)[0],
        },
        as_of=now(),
        allowed_visibility=actor.document_labels,
        idempotency_key=f"revision:{thesis_id}:v{thesis.version}",
    )
    candidate = candidate_from_execution(execution)
    if not candidate.payload or candidate.ai_status == "解析失败":
        raise ValidationFailed("Agent 未生成可用的修订候选")

    revision = assets.create_thesis_revision(uow, thesis_id=thesis_id, actor=actor)
    payload = _revision_payload(revision.payload, candidate.payload, hypotheses)
    revision = assets.update_thesis_revision(
        uow,
        draft_id=revision.draft_id,
        expected_revision=revision.revision,
        payload=payload,
        actor=actor,
    )
    audit.record(
        uow.audit,
        actor=actor.user_id,
        action="生成AI逻辑修订候选",
        object_type="thesis",
        object_id=thesis_id,
        detail={
            "run_id": candidate.run_id,
            "draft_id": revision.draft_id,
            "retrieved_document_ids": sorted({item.document_id for item in hits}),
            "requires_human_review": True,
        },
        model_version=str(candidate.payload.get("model_version") or "") or None,
    )
    return RevisionCandidate(execution=candidate, revision=revision)


def _recommendation_with_threshold(
    uow: UnitOfWork,
    *,
    runtime: InvestmentResearchAgent,
    security_id: str,
    recommendation: dict[str, Any],
    as_of: date,
) -> dict[str, Any]:
    """为一条目录指标追加只依赖事前观测的可审计阈值候选。"""

    result = dict(recommendation)
    metric_id = str(result.get("metric_id") or "")
    # 目录是关系类型的唯一事实来源；模型若返回不一致的标签，以目录口径校正，
    # 避免整批候选因一个 relation_type 拼写偏差被判为解析失败。
    catalog_relation = {
        "AUTO-SALES-M": "直接指标",
        "AUTO-EXPORT-SALES-M": "直接指标",
        "AUTO-BATTERY-INSTALL-M": "直接指标",
        "FIN-REVENUE-Q": "代理指标",
        "FIN-REVENUE-YOY-Q": "直接指标",
        "FIN-GROSS-MARGIN-Q": "直接指标",
        "FIN-NET-PROFIT-Q": "直接指标",
    }
    if metric_id in catalog_relation:
        result["relation_type"] = catalog_relation[metric_id]
    if not result.get("unit"):
        result["unit"] = {
            "AUTO-SALES-M": "辆",
            "AUTO-EXPORT-SALES-M": "辆",
            "AUTO-BATTERY-INSTALL-M": "GWh",
            "FIN-REVENUE-Q": "元",
            "FIN-GROSS-MARGIN-Q": "%",
        }.get(metric_id, "")
    direction = result.get("expected_direction")
    if not metric_id or not direction or direction == "波动":
        result["threshold_suggestion"] = {
            "value": None,
            "method": "direction_requires_bounds" if direction == "波动" else "missing_direction",
            "formula": "未计算",
            "rationale": (
                "波动方向需要研究员分别填写上限或下限，不能由单个候选值代替。"
                if direction == "波动"
                else "指标目录尚未确定预期方向，不能选择失效侧。"
            ),
            "sample_count": 0,
            "source_periods": [],
            "source_ids": [],
            "confidence": 0.0,
            "warnings": [
                "请研究员确认上限或下限。" if direction == "波动" else "请研究员先确认预期方向。"
            ],
            "requires_human_review": True,
        }
        return result
    source_rows = [
        item
        for item in uow.observations.list_for_metric(security_id, metric_id)
        if item.actual_value is not None
        and item.metric_version == result.get("metric_version")
        and item.observation_date <= as_of
    ]
    latest_before_refresh = max(source_rows, key=lambda item: item.observation_date, default=None)
    needs_refresh = (
        latest_before_refresh is None
        or latest_before_refresh.observation_date < as_of - timedelta(days=180)
    )
    if (
        needs_refresh
        and metric_id
        in {
            "FIN-REVENUE-Q",
            "FIN-REVENUE-YOY-Q",
            "FIN-GROSS-MARGIN-Q",
            "AUTO-SALES-M",
            "AUTO-EXPORT-SALES-M",
            "AUTO-BATTERY-INSTALL-M",
        }
        and uow.observations.__class__.__module__.startswith("app.db.")
    ):
        _refresh_metric_history(
            uow,
            security_id=security_id,
            metric_id=metric_id,
            force_refresh=latest_before_refresh is not None,
        )
        source_rows = [
            item
            for item in uow.observations.list_for_metric(security_id, metric_id)
            if item.actual_value is not None
            and item.metric_version == result.get("metric_version")
            and item.observation_date <= as_of
        ]
    observations = [
        ThresholdObservation(
            period=item.period,
            value=cast(Decimal, item.actual_value),
            available_on=item.observation_date,
            source_id=item.source_document_id or f"metric:{metric_id}",
        )
        for item in source_rows
    ]
    suggestion = runtime.suggest_metric_threshold(
        observations=observations,
        expected_direction=str(direction),
        as_of=as_of,
    )
    result["threshold_suggestion"] = _jsonable(asdict(suggestion))
    latest = max(source_rows, key=lambda item: item.observation_date, default=None)
    result["data_status"] = (
        "missing"
        if latest is None
        else "stale"
        if latest.observation_date < as_of - timedelta(days=180)
        else "available"
    )
    result["observations"] = [
        {
            "period": item.period,
            "value": str(item.actual_value),
            "published_on": item.observation_date.isoformat(),
            "acquired_at": item.ingested_at.isoformat() if item.ingested_at else None,
            "source": item.source_document_id or item.data_version,
            "data_version": item.data_version,
        }
        for item in sorted(source_rows, key=lambda row: row.observation_date)[-8:]
    ]
    return result


def _refresh_metric_history(
    uow: UnitOfWork, *, security_id: str, metric_id: str, force_refresh: bool = False
) -> None:
    """缺少历史时调用受控真实数据工具并写回观测表。

    采集失败不伪造数值；本次推荐仍返回 missing/stale，供研究员判断。
    """
    try:
        if metric_id in {"AUTO-SALES-M", "AUTO-EXPORT-SALES-M", "AUTO-BATTERY-INSTALL-M"}:
            candidates = fetch_periodic_metrics(
                security_id=security_id,
                cache_dir=__import__("pathlib").Path(__file__).resolve().parents[2]
                / ".runtime"
                / "metric-notices",
            )
        else:
            cache_path = (
                __import__("pathlib").Path(__file__).resolve().parents[2]
                / "real_data"
                / "raw"
                / "financials.json"
            )
            payload = (
                json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
            )
            rows = (payload.get("metrics") or {}).get(security_id) or []
            # 在线服务只消费已审核的本地快照；刷新由 analytics 离线管道负责，
            # 避免请求链路写项目数据或依赖离线分析包。
            data_version = str(payload.get("data_version") or "eastmoney-financial-v1")
            field = {
                "FIN-REVENUE-Q": "revenue",
                "FIN-REVENUE-YOY-Q": "revenue_yoy",
                "FIN-GROSS-MARGIN-Q": "gross_margin",
            }.get(metric_id)
            if field is None:
                return
            unit = "元" if field == "revenue" else "%"
            candidates = []
            for row in rows:
                if row.get("disclosure_date") and row.get(field) is not None:
                    candidates.append(
                        CompanyMetricObservation(
                            metric_id=metric_id,
                            metric_version="v1.0",
                            period=str(row.get("period")),
                            value=str(row.get(field)),
                            unit=unit,
                            observation_date=date.fromisoformat(str(row["disclosure_date"])),
                            source_document_id=f"EM-FIN-{security_id}-{row['period']}",
                            source_url="",
                            data_version=data_version,
                        )
                    )
        existing = {
            item.period for item in uow.observations.list_for_metric(security_id, metric_id)
        }
        for item in candidates:
            if item.metric_id != metric_id or item.period in existing:
                continue
            uow.observations.add(
                ObservationRecord(
                    security_id=security_id,
                    metric_id=metric_id,
                    metric_version="v1.0",
                    period=item.period,
                    period_type="单月" if item.unit in {"辆", "GWh"} else "单季度",
                    observation_date=item.observation_date,
                    actual_value=Decimal(str(item.value)),
                    unit=item.unit,
                    source_document_id=item.source_document_id,
                    data_version=item.data_version,
                )
            )
    except Exception:
        # 外部数据源不可用时保持可审计的 missing 状态，不阻断 Agent 候选返回。
        return


def _visible_thesis(uow: UnitOfWork, thesis_id: str, actor: Actor):
    thesis = uow.thesis.get(thesis_id)
    if thesis is None:
        raise NotVisible("逻辑不存在或无访问权限")
    permission.ensure_thesis_visible(
        actor,
        thesis_id=thesis_id,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    )
    return thesis


def _visible_hypothesis(uow: UnitOfWork, thesis_id: str, hypothesis_id: str, actor: Actor):
    thesis = _visible_thesis(uow, thesis_id, actor)
    hypothesis = uow.thesis.get_hypothesis(hypothesis_id)
    if hypothesis is None or hypothesis.thesis_id != thesis_id:
        raise NotVisible("假设不存在或无访问权限")
    return thesis, hypothesis


def _trend_calc_result(trend) -> dict[str, Any]:
    result = trend.result
    if result is None:
        return {
            "metric_id": trend.metric_id,
            "status": "信息不足",
            "note": trend.note,
            "period_type": trend.period_type,
            "unit": trend.unit,
            "metric_version": trend.metric_version,
        }
    return {
        "metric_id": trend.metric_id,
        "periods": list(result.periods),
        "values": [str(item) for item in result.values],
        "direction": result.direction,
        "slope": str(result.slope) if result.slope is not None else None,
        "consecutive_decline": result.consecutive_decline,
        "consecutive_below_expectation": result.consecutive_below_expectation,
        "verdict": result.verdict.value,
        "note": trend.note,
        "period_type": trend.period_type,
        "unit": trend.unit,
        "metric_version": trend.metric_version,
        "data_version": trend.data_version,
    }


def _calc_fingerprint(calc_result: dict[str, Any]) -> str:
    """生成短且稳定的计算结果标识，供 Runtime 幂等键使用。"""

    raw = json.dumps(calc_result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:20]


def _review_records(
    uow: UnitOfWork, thesis_id: str, period_start: date, period_end: date
) -> list[dict[str, Any]]:
    """只汇总已确认关系和区间内的审计动作，候选证据不会被写成正式结论。"""

    records: list[dict[str, Any]] = []
    for relation in uow.relations.list_for_thesis(thesis_id):
        if relation.status is not ConfirmationStatus.CONFIRMED:
            continue
        evidence = uow.evidence.get(relation.evidence_id)
        if evidence is None or evidence.disclosed_at is None:
            continue
        if not period_start <= evidence.disclosed_at.date() <= period_end:
            continue
        records.append(
            {
                "record_type": "confirmed_evidence",
                "evidence_id": evidence.evidence_id,
                "hypothesis_id": relation.hypothesis_id,
                "fact": evidence.fact_excerpt or "",
                "impact_direction": relation.direction.value,
                "evidence_locator": evidence.evidence_locator,
                "disclosed_at": evidence.disclosed_at.isoformat(),
                "confirmed_by": relation.reviewed_by,
            }
        )
    for item in uow.audit.list_for_object("thesis", thesis_id):
        if item.occurred_at is None or not period_start <= item.occurred_at.date() <= period_end:
            continue
        records.append(
            {
                "record_type": "audit",
                "summary": item.action,
                "actor": item.actor,
                "occurred_at": item.occurred_at.isoformat(),
                "detail": item.detail or {},
            }
        )
    records.sort(key=lambda item: str(item.get("disclosed_at") or item.get("occurred_at") or ""))
    return records


def _revision_payload(
    base_payload: dict[str, Any],
    candidate: dict[str, Any],
    current_hypotheses: list,
) -> dict[str, Any]:
    """把新逻辑候选映射到现有假设 ID，避免绕过版本服务的身份约束。"""

    payload = deepcopy(base_payload)
    thesis_payload = payload.get("thesis")
    thesis_payload = dict(thesis_payload) if isinstance(thesis_payload, dict) else {}
    thesis_payload["title"] = str(candidate.get("title") or thesis_payload.get("title") or "")
    thesis_payload["core_view"] = str(
        candidate.get("core_view") or thesis_payload.get("core_view") or ""
    )
    payload["thesis"] = thesis_payload

    generated = candidate.get("hypotheses")
    generated = generated if isinstance(generated, list) else []
    current_payload = payload.get("hypotheses")
    current_payload = current_payload if isinstance(current_payload, list) else []
    by_id = {
        str(item.get("hypothesis_id")): dict(item)
        for item in current_payload
        if isinstance(item, dict) and item.get("hypothesis_id")
    }
    revised: list[dict[str, Any]] = []
    for index, current in enumerate(current_hypotheses):
        item = by_id.get(current.hypothesis_id, _jsonable(asdict(current)))
        suggestion = (
            generated[index]
            if index < len(generated) and isinstance(generated[index], dict)
            else {}
        )
        if suggestion.get("statement"):
            item["statement"] = str(suggestion["statement"])
        if suggestion.get("hypothesis_type"):
            item["hypothesis_type"] = str(suggestion["hypothesis_type"])
        if suggestion.get("importance") in {"核心", "辅助"}:
            item["importance"] = str(suggestion["importance"])
        revised.append(item)
    payload["hypotheses"] = revised
    payload["ai_revision_candidate"] = {
        "requires_human_review": True,
        "risks": candidate.get("risks") or [],
        "invalidation_suggestions": candidate.get("invalidation_suggestions") or [],
        "citations": candidate.get("citations") or [],
        "model_version": candidate.get("model_version"),
        "prompt_version": candidate.get("prompt_version"),
        "generated_at": candidate.get("generated_at"),
    }
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and hasattr(value, "name"):
        return value.value
    return value
