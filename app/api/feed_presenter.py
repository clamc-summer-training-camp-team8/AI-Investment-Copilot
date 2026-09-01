"""将证据聚合值对象转换成面向研究员的可读响应。"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.domain import EvidenceFeedRecord, LogicChangeDigestRecord
from app.schemas.thesis import EvidenceFeedItemOut, ThemeImpactOut, ValidationItemOut


def _validation(code: str, label: str, ok: bool, passed: str, failed: str) -> ValidationItemOut:
    return ValidationItemOut(
        code=code,
        label=label,
        status="passed" if ok else "failed",
        message=passed if ok else failed,
    )


def to_feed_item(record: EvidenceFeedRecord, *, actor_id: str) -> EvidenceFeedItemOut:
    """验证项只解释已经持久化的数据，不在读取时访问外部网站。"""
    parsed = urlparse(record.source_url or "")
    external_source = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    traceable = bool(record.source_document_id and record.source_document_title)
    complete = bool(
        record.security_id
        and record.security_name
        and record.fact_excerpt
        and record.disclosed_at
        and record.hypothesis_statement
    )
    in_window = bool(
        record.disclosed_at
        and record.disclosed_at.date() >= record.thesis_established_on
        and (
            record.thesis_horizon_end_on is None
            or record.disclosed_at.date() <= record.thesis_horizon_end_on
        )
    )
    validations = [
        _validation(
            "source_traceable",
            "来源可追溯",
            traceable,
            "来源文档及原文定位齐全。" if not external_source else "来源文档、标题和公开链接齐全。",
            "来源文档信息不完整，无法回查原文。",
        ),
        _validation(
            "required_fields_complete",
            "关键字段完整",
            complete,
            "证券、事实摘录、披露时间和假设文本齐全。",
            "证据摘要存在缺失字段。",
        ),
        ValidationItemOut(
            code="within_observation_window",
            label="处于观察窗口",
            status="passed" if in_window else "warning",
            message="披露时间处于逻辑观察窗口内。"
            if in_window
            else "披露时间不在当前逻辑观察窗口内，请人工复核。",
        ),
        ValidationItemOut(
            code="same_security",
            label="同一证券",
            status="passed",
            message="证据与目标逻辑证券一致。",
        ),
        ValidationItemOut(
            code="hypothesis_belongs_to_thesis",
            label="假设归属有效",
            status="passed",
            message="目标假设属于当前投资逻辑。",
        ),
    ]
    return EvidenceFeedItemOut(
        evidence_id=record.evidence_id,
        relation_id=record.relation_id,
        security_id=record.security_id,
        security_name=record.security_name,
        thesis_id=record.thesis_id,
        thesis_title=record.thesis_title,
        thesis_core_view=record.thesis_core_view,
        source_document_id=record.source_document_id or "",
        hypothesis_id=record.hypothesis_id,
        hypothesis_statement=record.hypothesis_statement,
        source_document_title=record.source_document_title or "未命名公开资料",
        fact_excerpt=record.fact_excerpt or "事实摘录待补充",
        disclosed_at=record.disclosed_at,
        ingested_at=record.ingested_at,
        occurred_at=record.occurred_at,
        source_url=record.source_url or "",
        direction=record.direction.value,
        strength=record.strength,
        ai_confidence=record.ai_confidence,
        confirmation_status=record.confirmation_status.value,
        priority=record.priority,
        can_manage=record.thesis_owner == actor_id,
        validation_items=validations,
    )


def aggregate_feed_items(
    items: list[EvidenceFeedItemOut], *, daily: bool = False
) -> list[EvidenceFeedItemOut]:
    """Collapse atomic evidence into reviewer-facing daily impact themes.

    The normal daily unit is company + thesis.  News, announcements, reports
    and earnings releases are evidence inputs, not separate reviewer-facing
    themes.  The reviewer sees one consolidated change to the active investment
    thesis and can drill into its hypothesis paths and source materials.
    Historical mode keeps its 14-day directional grouping for retrospective
    analysis.
    """

    groups: dict[tuple[object, ...], list[EvidenceFeedItemOut]] = {}
    if daily:
        groups = _daily_theme_groups(items)
    else:
        for item in items:
            window = item.disclosed_at.date().toordinal() // 14
            key = (item.security_id, item.thesis_id, item.direction, window)
            groups.setdefault(key, []).append(item)
    divergent_hypotheses = _divergent_hypotheses(items) if daily else set()
    cards: list[EvidenceFeedItemOut] = []
    for group in groups.values():
        primary = sorted(group, key=_aggregation_rank)[0]
        hypotheses = list(dict.fromkeys(item.hypothesis_statement for item in group))
        source_count = len(
            {item.source_document_id or item.source_document_title for item in group}
        )
        support_count = sum(item.direction == "支持" for item in group)
        conflict_count = sum(item.direction == "冲突" for item in group)
        theme_impacts = _theme_impacts(group, divergent_hypotheses)
        theme_direction = _theme_direction(support_count, conflict_count)
        summary = (
            _daily_theme_summary(primary, hypotheses, theme_direction)
            if daily
            else (
                f"近两周 {source_count} 个来源形成 {len(group)} 条原子候选；"
                f"主影响关联“{primary.hypothesis_statement}”。"
            )
        )
        cards.append(
            primary.model_copy(
                update={
                    "aggregation_summary": summary,
                    "atomic_evidence_count": len(group),
                    "source_document_count": source_count,
                    "support_evidence_count": support_count,
                    "conflict_evidence_count": conflict_count,
                    "affected_hypothesis_count": len(hypotheses),
                    "secondary_hypotheses": [
                        value for value in hypotheses if value != primary.hypothesis_statement
                    ],
                    "theme_impacts": theme_impacts,
                    "theme_direction": theme_direction,
                }
            )
        )
    return sorted(cards, key=_aggregation_rank)


def apply_daily_logic_digests(
    cards: list[EvidenceFeedItemOut],
    digests: dict[tuple[str, str], LogicChangeDigestRecord],
) -> list[EvidenceFeedItemOut]:
    """用已持久化的 LLM 日归并替换卡片摘要，不隐藏任何原始计数或下钻入口。"""
    result: list[EvidenceFeedItemOut] = []
    for card in cards:
        digest = digests.get((card.security_id, card.thesis_id))
        if digest is None:
            result.append(card)
            continue
        statements = {
            impact.hypothesis_id: impact.hypothesis_statement for impact in card.theme_impacts
        }
        impacts = [
            ThemeImpactOut(
                hypothesis_id=str(item["hypothesis_id"]),
                hypothesis_statement=statements.get(str(item["hypothesis_id"]), "关联假设"),
                direction=(
                    "中性"
                    if str(item.get("direction")) in {"分歧", "待观察"}
                    else str(item.get("direction") or "中性")
                ),
                evidence_count=max(1, len(item.get("evidence_ids") or [])),
                has_conflicting_evidence=str(item.get("direction")) == "分歧",
            )
            for item in digest.hypothesis_impacts
            if str(item.get("hypothesis_id")) in statements
        ]
        theme_direction = {
            "支持": "support",
            "冲突": "conflict",
            "混合": "mixed",
            "待观察": "neutral",
        }.get(digest.overall_direction, "neutral")
        result.append(
            card.model_copy(
                update={
                    "aggregation_summary": digest.summary,
                    "theme_impacts": impacts or card.theme_impacts,
                    "theme_direction": theme_direction,
                    "affected_hypothesis_count": len(impacts) or card.affected_hypothesis_count,
                }
            )
        )
    return result


def _daily_theme_groups(
    items: list[EvidenceFeedItemOut],
) -> dict[tuple[object, ...], list[EvidenceFeedItemOut]]:
    """Combine a day's evidence into one active investment-logic change."""
    groups: dict[tuple[object, ...], list[EvidenceFeedItemOut]] = {}
    for item in items:
        groups.setdefault((item.security_id, item.thesis_id), []).append(item)
    return groups


def _daily_theme_summary(
    primary: EvidenceFeedItemOut, hypotheses: list[str], theme_direction: str
) -> str:
    direction = {
        "support": "得到增强",
        "conflict": "面临压力",
        "mixed": "出现分歧，需要复核",
        "neutral": "暂未出现明确方向",
    }[theme_direction]
    return f"围绕“{primary.thesis_core_view}”，今日资料综合显示该主投资逻辑{direction}。"


def _divergent_hypotheses(items: list[EvidenceFeedItemOut]) -> set[tuple[str, str, str]]:
    directions: dict[tuple[str, str, str], set[str]] = {}
    for item in items:
        directions.setdefault((item.security_id, item.thesis_id, item.hypothesis_id), set()).add(
            item.direction
        )
    return {key for key, values in directions.items() if "支持" in values and "冲突" in values}


def _theme_impacts(
    items: list[EvidenceFeedItemOut], divergent_hypotheses: set[tuple[str, str, str]]
) -> list[ThemeImpactOut]:
    grouped: dict[str, list[EvidenceFeedItemOut]] = {}
    for item in items:
        grouped.setdefault(item.hypothesis_id, []).append(item)
    return [
        ThemeImpactOut(
            hypothesis_id=group[0].hypothesis_id,
            hypothesis_statement=group[0].hypothesis_statement,
            direction=_hypothesis_direction(group),
            evidence_count=len(group),
            has_conflicting_evidence=(
                group[0].security_id,
                group[0].thesis_id,
                group[0].hypothesis_id,
            )
            in divergent_hypotheses,
        )
        for group in grouped.values()
    ]


def _hypothesis_direction(items: list[EvidenceFeedItemOut]) -> str:
    """A conflicting path stays visible as a neutral path plus an explicit flag."""
    support_count = sum(item.direction == "支持" for item in items)
    conflict_count = sum(item.direction == "冲突" for item in items)
    if support_count and conflict_count:
        return "中性"
    if conflict_count:
        return "冲突"
    if support_count:
        return "支持"
    return "中性"


def _aggregation_rank(item: EvidenceFeedItemOut) -> tuple[int, int, int, float, float]:
    priority = {"high": 0, "medium": 1, "low": 2}[item.priority]
    direction = {"冲突": 0, "支持": 1, "中性": 2}[item.direction]
    strength = {"高": 0, "中": 1, "低": 2}.get(item.strength or "", 3)
    return (
        priority,
        direction,
        strength,
        -float(item.ai_confidence or 0),
        -item.disclosed_at.timestamp(),
    )


def _theme_direction(support_count: int, conflict_count: int) -> str:
    if support_count and conflict_count:
        return "mixed"
    if conflict_count:
        return "conflict"
    if support_count:
        return "support"
    return "neutral"
