"""版本快照（PRD 5.3）。

规则：

| 情形 | 是否产生版本 |
| --- | --- |
| 草稿阶段连续保存 | 否 |
| 发布 | 是，V1 |
| 核心观点 / 关键假设 / 预期 / 失效条件 / 状态的正式修改 | 是 |
| 证据确认 | 写时间线；若导致关键字段变化，则同时产生新版本 |

**历史版本冻结当时可得信息，禁止用未来信息覆盖历史记录。** 快照生成后不允许
UPDATE，发现有误的正确做法是生成新版本并说明原因。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal

from app.services.ports import (
    HypothesisRecord,
    MetricMappingRecord,
    ThesisRecord,
    UnitOfWork,
    VersionRecord,
    VersionRepo,
)

# 这些字段的正式修改触发新版本
KEY_FIELDS = frozenset(
    {
        "core_view",
        "title",
        "direction",
        "status",
        "established_on",
        "horizon_end_on",
        "invalidation_require_all",
    }
)

TRIGGER_PUBLISH = "发布"
TRIGGER_FIELD_EDIT = "字段修改"
TRIGGER_EVIDENCE = "证据确认"
TRIGGER_STATUS = "状态变更"
TRIGGER_REVIEW = "复核"


def build_snapshot(
    thesis: ThesisRecord,
    hypotheses: list[HypothesisRecord],
    mappings: list[MetricMappingRecord] | None = None,
    evidence: list[dict[str, object]] | None = None,
    data_cutoff_at: datetime | None = None,
    rule_version: str | None = None,
    model_versions: list[str] | None = None,
) -> dict[str, object]:
    """全字段快照。

    只序列化传入的数据，不回查数据库补字段——回查会把「当时可得信息」污染成
    「现在可得信息」，那就不是冻结快照了。
    """
    return {
        "thesis": {k: _plain(v) for k, v in asdict(thesis).items()},
        "hypotheses": [{k: _plain(v) for k, v in asdict(h).items()} for h in hypotheses],
        "metric_mappings": [
            {k: _plain(v) for k, v in asdict(mapping).items()} for mapping in (mappings or [])
        ],
        "evidence": evidence or [],
        "data_cutoff_at": _plain(data_cutoff_at) if data_cutoff_at else None,
        "rule_version": rule_version,
        "model_versions": sorted(set(model_versions or [])),
    }


def _plain(value: object) -> object:
    """转成 JSON 可存的形式。Decimal 转字符串避免浮点残留。"""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, frozenset | set):
        return sorted(str(v) for v in value)
    if isinstance(value, Decimal):
        # 转字符串，避免 JSON 序列化时退化成 float 引入浮点残留
        return str(value)
    if hasattr(value, "value") and hasattr(value, "name"):
        return value.value  # StrEnum
    return value


def changed_key_fields(before: ThesisRecord, after: ThesisRecord) -> list[str]:
    """比较两个状态，返回发生变化的关键字段。"""
    before_map, after_map = asdict(before), asdict(after)
    return sorted(f for f in KEY_FIELDS if before_map.get(f) != after_map.get(f))


def create(
    repo: VersionRepo,
    *,
    thesis: ThesisRecord,
    hypotheses: list[HypothesisRecord],
    triggered_by: str,
    created_by: str,
    change_reason: str | None = None,
    changed_fields: list[str] | None = None,
    mappings: list[MetricMappingRecord] | None = None,
    evidence: list[dict[str, object]] | None = None,
    data_cutoff_at: datetime | None = None,
    rule_version: str | None = None,
    model_versions: list[str] | None = None,
) -> VersionRecord:
    """生成新版本。版本号在 latest 基础上 +1，不接受调用方指定。"""
    latest = repo.latest(thesis.thesis_id)
    next_version = 1 if latest is None else latest.version + 1

    record = VersionRecord(
        thesis_id=thesis.thesis_id,
        version=next_version,
        snapshot=build_snapshot(
            thesis,
            hypotheses,
            mappings,
            evidence,
            data_cutoff_at,
            rule_version,
            model_versions,
        ),
        triggered_by=triggered_by,
        created_by=created_by,
        change_reason=change_reason,
        changed_fields=changed_fields or [],
        data_cutoff_at=data_cutoff_at,
        rule_version=rule_version,
        model_versions=sorted(set(model_versions or [])),
    )
    repo.add(record)
    return record


def evidence_snapshot(
    uow: UnitOfWork, thesis_id: str
) -> tuple[list[dict[str, object]], datetime | None, list[str]]:
    """Freeze confirmed evidence references and their model context at version time."""
    items: list[dict[str, object]] = []
    cutoff: datetime | None = None
    models: list[str] = []
    for record in uow.evidence.list_for_thesis(thesis_id):
        if record.confirmation_status.value != "已确认":
            continue
        items.append(
            {
                "evidence_id": record.evidence_id,
                "hypothesis_id": record.hypothesis_id,
                "event_id": record.event_id,
                "direction": record.direction.value,
                "evidence_locator": record.evidence_locator,
                "source_document_id": record.source_document_id,
                "disclosed_at": _plain(record.disclosed_at) if record.disclosed_at else None,
                "model_version": record.model_version,
                "prompt_version": record.prompt_version,
            }
        )
        if record.disclosed_at and (cutoff is None or record.disclosed_at > cutoff):
            cutoff = record.disclosed_at
        if record.model_version:
            models.append(record.model_version)
    return items, cutoff, sorted(set(models))
