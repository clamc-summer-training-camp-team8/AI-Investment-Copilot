"""事件抽取与方向枚举归一。

基线里方向取值有三套写法，必须显式映射而不是隐式相信输入：

| 来源 | 取值 |
| --- | --- |
| PRD 4.6 / `ImpactDirection` | 支持 / 冲突 / 中性 / 无关 |
| 样例 CSV、台账事件页、标注规范 | 支持 / 削弱 / 中性 / 不确定 |
| FLD-007 / `SignalDirection` | 正向 / 负向 / 中性 / 不确定 |

「削弱」对应「冲突」。**「不确定」在 ImpactDirection 里没有对应值**——这是基线的
真实缺口，不能硬塞成「中性」：中性意味着已判断为无影响，不确定意味着尚未判断，
两者的处置动作不同（前者可入证据链，后者必须进人工队列）。因此这里映射为 None
并要求调用方走待复核路径。
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.core.enums import ImpactDirection, ReviewStatus, SignalDirection, Strength
from app.core.timeutil import BUSINESS_TZ, ensure_aware
from app.ingest.segmentation import event_fingerprint

# 台账与样例 CSV 的写法 → PRD 正式枚举
_IMPACT_ALIASES: dict[str, ImpactDirection | None] = {
    "支持": ImpactDirection.SUPPORT,
    "冲突": ImpactDirection.CONFLICT,
    "削弱": ImpactDirection.CONFLICT,
    "中性": ImpactDirection.NEUTRAL,
    "无关": ImpactDirection.IRRELEVANT,
    "不确定": None,
}

_SIGNAL_ALIASES: dict[str, SignalDirection] = {
    "支持": SignalDirection.POSITIVE,
    "正向": SignalDirection.POSITIVE,
    "削弱": SignalDirection.NEGATIVE,
    "冲突": SignalDirection.NEGATIVE,
    "负向": SignalDirection.NEGATIVE,
    "中性": SignalDirection.NEUTRAL,
    "不确定": SignalDirection.UNCERTAIN,
    "无关": SignalDirection.NEUTRAL,
}

# 强度：台账用 0~1 浮点，PRD 4.6 用高/中/低。分档阈值基线未规定，
# 这里取三等分并记录在此，改动需同步 contracts 与前端展示。
STRENGTH_HIGH = Decimal("0.7")
STRENGTH_MEDIUM = Decimal("0.4")


class DirectionUnmappable(ValueError):
    """方向取值无法映射到 ImpactDirection，必须进人工队列。"""


def to_impact_direction(raw: str) -> ImpactDirection:
    """归一为 ImpactDirection。「不确定」抛错，由调用方转人工。"""
    key = raw.strip()
    if key not in _IMPACT_ALIASES:
        raise DirectionUnmappable(f"未知的影响方向取值: {raw!r}")
    mapped = _IMPACT_ALIASES[key]
    if mapped is None:
        raise DirectionUnmappable(
            f"方向 {raw!r} 表示尚未判断，不等于中性，必须进人工队列而非写入证据链"
        )
    return mapped


def to_signal_direction(raw: str) -> SignalDirection:
    key = raw.strip()
    if key not in _SIGNAL_ALIASES:
        raise DirectionUnmappable(f"未知的信号方向取值: {raw!r}")
    return _SIGNAL_ALIASES[key]


def to_strength_bucket(score: Decimal | float | str | None) -> Strength | None:
    """0~1 分数转高/中/低。缺失返回 None，不猜测。"""
    if score is None:
        return None
    value = Decimal(str(score))
    if value >= STRENGTH_HIGH:
        return Strength.HIGH
    if value >= STRENGTH_MEDIUM:
        return Strength.MEDIUM
    return Strength.LOW


@dataclass(frozen=True)
class ExtractedEvent:
    """从资料中抽取的结构化事件。

    occurred_on 与 disclosure_time 分开存储：前者是事实发生时间（可空），后者是
    首次公开可得时间（必填，FLD-006）。合成一个字段会让 DQ-003 的泄露判定失去依据。
    """

    event_id: str
    document_id: str
    security_id: str | None
    event_type: str
    summary: str
    disclosure_time: datetime
    fingerprint: str
    occurred_on: date | None = None
    hypothesis_id: str | None = None
    impact_direction: ImpactDirection | None = None
    strength_score: Decimal | None = None
    horizon: str | None = None
    is_direct: bool | None = None
    evidence_locator: str | None = None
    ai_confidence: Decimal | None = None
    review_status: ReviewStatus | None = None
    needs_human_review: bool = False
    review_reason: str = ""


_EVENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "订单": ("订单", "中标", "合同"),
    "政策": ("政策", "补贴", "监管", "关税"),
    "管理层表述": ("管理层", "展望", "指引", "说明会"),
    "业绩": ("财报", "毛利率", "收入同比", "业绩"),
}

_TITLE_ONLY_PATTERN = re.compile(r"^(?:[^\n]{0,80})?(?:公告|报告|通知|说明书)$")


def classify_event_type(text: str) -> str:
    """关键词分类。这是 local 提供者的确定性实现，不调模型。"""
    for event_type, keywords in _EVENT_KEYWORDS.items():
        if any(k in text for k in keywords):
            return event_type
    return "其他"


def _parse_dt(value: str) -> datetime:
    text = value.strip()
    fmt = "%Y-%m-%d %H:%M" if " " in text else "%Y-%m-%d"
    return ensure_aware(datetime.strptime(text, fmt), assume=BUSINESS_TZ)


def _parse_bool(value: str | None) -> bool | None:
    text = (value or "").strip()
    if text in ("直接", "TRUE", "true", "是"):
        return True
    if text in ("间接", "FALSE", "false", "否"):
        return False
    return None


def _dec(value: str | None) -> Decimal | None:
    text = (value or "").strip()
    return Decimal(text) if text else None


def load_annotated_events(path: Path) -> list[ExtractedEvent]:
    """读取样例事件人工标注 CSV。

    方向不可映射（「不确定」）时不丢弃，标记 needs_human_review 并保留原因——
    丢弃会让样本静默减少，评测口径失真。
    """
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    events: list[ExtractedEvent] = []
    for row in rows:
        summary = row["evidence"].strip()
        direction: ImpactDirection | None = None
        needs_review = False
        reason = ""
        try:
            direction = to_impact_direction(row["direction"])
        except DirectionUnmappable as exc:
            needs_review = True
            reason = str(exc)

        events.append(
            ExtractedEvent(
                event_id=row["event_id"].strip(),
                document_id=row["document_id"].strip(),
                security_id=(row.get("security_id") or "").strip() or None,
                event_type=row["event_type"].strip(),
                summary=summary,
                occurred_on=_parse_dt(row["event_time"]).date() if row.get("event_time") else None,
                disclosure_time=_parse_dt(row["disclosure_time"]),
                fingerprint=event_fingerprint(row["document_id"], summary),
                hypothesis_id=(row.get("hypothesis_id") or "").strip() or None,
                impact_direction=direction,
                strength_score=_dec(row.get("strength")),
                horizon=(row.get("horizon") or "").strip() or None,
                is_direct=_parse_bool(row.get("direct")),
                evidence_locator=None,
                needs_human_review=needs_review,
                review_reason=reason,
            )
        )
    return events


def dedupe_events(
    events: list[ExtractedEvent],
) -> tuple[list[ExtractedEvent], dict[str, list[str]]]:
    """按指纹合并重复事件，返回保留事件与来源集合。

    FR-R-005：重复事件合并并保留来源集合，不重复提醒。保留最早披露时间的那条，
    因为披露时间是收益窗口起点，取晚的会造成时间起点后移。
    """
    by_fingerprint: dict[str, ExtractedEvent] = {}
    sources: dict[str, list[str]] = {}

    for event in sorted(events, key=lambda e: e.disclosure_time):
        existing = by_fingerprint.get(event.fingerprint)
        if existing is None:
            by_fingerprint[event.fingerprint] = event
            sources[event.fingerprint] = [event.document_id]
        elif event.document_id not in sources[event.fingerprint]:
            sources[event.fingerprint].append(event.document_id)

    kept = list(by_fingerprint.values())
    return kept, sources


def extract_events_from_segments(
    document_id: str,
    security_id: str | None,
    segments: list[tuple[str, str]],
    *,
    disclosure_time: datetime,
) -> list[ExtractedEvent]:
    """从切片中抽取候选事件（local 规则实现）。

    segments 为 (locator, content)。每个含数值或关键词的段落产出一个候选事件，
    带上 locator——没有 locator 的事件无法进入正式证据链（DQ-005）。
    """
    results: list[ExtractedEvent] = []
    for index, (locator, content) in enumerate(segments, start=1):
        normalized = content.strip()
        # 纯标题不是可供核验的事实。否则“XX订单公告”和它的正文
        # 会各产生一条雷达候选，形成重复提醒。
        if _TITLE_ONLY_PATTERN.fullmatch(normalized):
            continue
        event_type = classify_event_type(normalized)
        has_number = bool(re.search(r"\d+(\.\d+)?%|\d+", normalized))
        if event_type == "其他" and not has_number:
            continue
        results.append(
            ExtractedEvent(
                event_id=f"{document_id}-EVT-{index}",
                document_id=document_id,
                security_id=security_id,
                event_type=event_type,
                summary=normalized[:500],
                disclosure_time=disclosure_time,
                # 事件指纹不包含文档 ID，否则同一公告的多源转载永远
                # 无法合并。证券维度避免不同公司的相同表述碰撞。
                fingerprint=event_fingerprint(security_id or "unassigned", normalized),
                evidence_locator=locator,
            )
        )
    return results
