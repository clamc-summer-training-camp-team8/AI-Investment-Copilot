"""将证据聚合值对象转换成面向研究员的可读响应。"""

from __future__ import annotations

from urllib.parse import urlparse

from app.core.domain import EvidenceFeedRecord
from app.schemas.thesis import EvidenceFeedItemOut, ValidationItemOut


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
        hypothesis_id=record.hypothesis_id,
        hypothesis_statement=record.hypothesis_statement,
        source_document_title=record.source_document_title or "未命名公开资料",
        fact_excerpt=record.fact_excerpt or "事实摘录待补充",
        disclosed_at=record.disclosed_at,
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
