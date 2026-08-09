"""用真实公开案例跑一轮 MVP 闭环验证。

数据放 `real_data/`（`.gitignore` 已排除）。仓库禁止提交真实公司财务数据
（`tests/README.md`），因此脚本与结论进仓库、数据不进。缺目录时给出提示并退出，
不静默跳过——静默跳过会让「没跑」看起来像「跑过了」。

不连数据库：闭环的正确性在编排逻辑，用内存仓储就能验证，而 DB 行为由
`tests/integration/db` 覆盖。这样这个脚本在任何环境都能跑。

用法：
    python -m scripts.run_real_case
    python -m scripts.run_real_case --json     # 输出机器可读结果
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.ai.gateway import Gateway
from app.core.config import PROJECT_ROOT, settings
from app.core.domain import (
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ThesisRecord,
)
from app.core.enums import (
    ConfirmationStatus,
    ExpectationDirection,
    Importance,
    ThesisStatus,
)
from app.core.timeutil import BUSINESS_TZ, ensure_aware
from app.ingest.events import load_annotated_events
from app.ingest.parsers.text import parse_sample_pack
from app.ingest.segmentation import segment_document
from app.services import evidence as evidence_service
from app.services import status as status_service
from app.services.permission import Actor
from app.workers import change_chain
from tests.fakes import build_fake_uow

REAL_DATA_DIR = PROJECT_ROOT / "real_data"

THESIS_ID = "THS-SG-001"
SECURITY_ID = "300274"
# 逻辑建立日。2024Q4 的观察期早于这个日期，应被窗口裁剪排除——真实数据里
# 2024Q4 毛利率 27.48% 已低于 30% 预期，不裁剪就会在建卡当天误报风险。
ESTABLISHED_ON = date(2025, 1, 10)
RESEARCHER = Actor(user_id="示例研究员", teams=frozenset({"权益研究"}))

# 三条核心假设，与样例案例 THS-DEMO-001 的结构一一对应。
# 阈值来自 DOC-SG-001 的研究员预期，不是模型填的（PRD 10.1 限制）。
HYPOTHESES: list[tuple[str, str, str, str, ExpectationDirection, str, int]] = [
    (
        "HYP-SG-001",
        "全球储能装机需求保持增长",
        "行业",
        "MET-003",
        ExpectationDirection.HIGHER_BETTER,
        "0.00",
        2,
    ),
    (
        "HYP-SG-002",
        "新增海外订单能够按计划转化为收入",
        "经营",
        "MET-001",
        ExpectationDirection.HIGHER_BETTER,
        "0.30",
        2,
    ),
    (
        "HYP-SG-003",
        "海外项目盈利质量稳定",
        "盈利",
        "MET-002",
        ExpectationDirection.NOT_BELOW_THRESHOLD,
        "0.30",
        1,
    ),
]

# 参与 thesis 级失效条件的假设。DOC-SG-001 的失效条件是「收入同比连续两个季度
# 低于预期 **且** 毛利率低于 30%」，只涉及这两条，行业装机不在条件里。
INVALIDATION_HYPOTHESES = ["HYP-SG-002", "HYP-SG-003"]


@dataclass
class Result:
    documents: int
    segments: int
    events: int
    candidates: int
    confirmed: int
    suggestion_status: str
    suggestion_reasons: list[str]
    final_status: str
    versions: int
    audit_actions: list[str]
    invalidation_note: str
    metric_findings: list[dict[str, str]]


def _require_data() -> None:
    missing = [
        name
        for name in ("documents.txt", "observations.csv", "events.csv")
        if not (REAL_DATA_DIR / name).is_file()
    ]
    if missing:
        print(f"缺少真实数据文件：{'、'.join(missing)}", file=sys.stderr)
        print(f"请按 {REAL_DATA_DIR / 'README.md'} 准备数据后重跑。", file=sys.stderr)
        print("真实数据不进版本控制，需要本地放置。", file=sys.stderr)
        raise SystemExit(2)


def _load_observations(path: Path) -> list[ObservationRecord]:
    """读观测值。

    披露时间必须带时区（DQ-003 的判定依据）；单位与口径随行走，不同 period_type
    的值禁止混算，由 app.calc 的 _assert_comparable 在计算时拦下。
    """
    records: list[ObservationRecord] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            ensure_aware(
                datetime.strptime(row["disclosure_time"].strip(), "%Y-%m-%d %H:%M"),
                assume=BUSINESS_TZ,
            )
            records.append(
                ObservationRecord(
                    security_id=row["security_id"].strip(),
                    metric_id=row["metric_id"].strip(),
                    period=row["period"].strip(),
                    observation_date=date.fromisoformat(row["observation_date"].strip()),
                    unit=row["unit"].strip(),
                    actual_value=Decimal(row["actual_value"]),
                    expected_value=Decimal(row["expected_value"]),
                    metric_version=row["metric_version"].strip(),
                    period_type=row["period_type"].strip(),
                    source_document_id=row["source_document_id"].strip(),
                    data_version=row["data_version"].strip(),
                )
            )
    return records


def _seed(uow: Any) -> None:
    uow.thesis.add(
        ThesisRecord(
            thesis_id=THESIS_ID,
            security_id=SECURITY_ID,
            title="海外储能需求增长推动收入与利润改善",
            direction="看多",
            core_view=("海外大型储能需求持续增长，将在未来四个季度推动储能分部收入和利润改善"),
            established_on=ESTABLISHED_ON,
            owner=RESEARCHER.user_id,
            status=ThesisStatus.VALIDATING,
            visibility="团队",
            team="权益研究",
            version=1,
            horizon_end_on=date(2026, 1, 10),
            next_review_at=date(2026, 4, 15),
            source_document_id="DOC-SG-001",
            # 真实数据，不是演示数据
            is_illustrative=False,
            invalidation_require_all=True,
            invalidation_hypotheses=INVALIDATION_HYPOTHESES,
        )
    )

    for hid, statement, htype, metric, direction, threshold, periods in HYPOTHESES:
        uow.thesis.add_hypothesis(
            HypothesisRecord(
                hypothesis_id=hid,
                thesis_id=THESIS_ID,
                statement=statement,
                hypothesis_type=htype,
                importance=Importance.CORE,
                expected_direction=direction,
            )
        )
        uow.thesis.add_mapping(
            MetricMappingRecord(
                mapping_id=f"MAP-{hid}",
                hypothesis_id=hid,
                metric_id=metric,
                expected_direction=direction,
                expected_value=Decimal(threshold),
                invalidation_threshold=Decimal(threshold),
                invalidation_consecutive_periods=periods,
                expectation_source="研究员人工录入，依据 DOC-SG-001",
                confirmation_status=ConfirmationStatus.CONFIRMED,
            )
        )


def run() -> Result:
    _require_data()
    uow = build_fake_uow()
    _seed(uow)

    for record in _load_observations(REAL_DATA_DIR / "observations.csv"):
        uow.observations.add(record)

    documents = dict(
        parse_sample_pack((REAL_DATA_DIR / "documents.txt").read_text(encoding="utf-8"))
    )
    segments_total = 0
    locator_by_event: dict[str, str] = {}
    events = load_annotated_events(REAL_DATA_DIR / "events.csv")

    for doc_id, parsed in documents.items():
        segments_total += len(segment_document(doc_id, parsed))

    for event in events:
        parsed = documents.get(event.document_id)
        if parsed is None:
            continue
        locator_by_event[event.event_id] = segment_document(event.document_id, parsed)[0].locator

    change = change_chain.process_events(
        uow,
        Gateway.build(settings),
        events=events,
        security_id=SECURITY_ID,
        actor=RESEARCHER,
        thresholds=settings.rules,
        locator_by_event=locator_by_event,
    )

    # 人工确认全部候选证据（FR-R-004 的「确认」动作）
    for candidate in list(uow.evidence.list_for_thesis(THESIS_ID)):
        evidence_service.handle(
            uow,
            evidence_id=candidate.evidence_id,
            action=evidence_service.CONFIRM,
            actor=RESEARCHER,
            thesis=uow.thesis.get(THESIS_ID),
            hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
            thresholds=settings.rules,
            note="依据公开披露确认",
        )

    suggestion = status_service.compute_suggestion(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        thresholds=settings.rules,
        today=date(2026, 4, 1),
    )
    saved = status_service.record_suggestion(
        uow, thesis=uow.thesis.get(THESIS_ID), suggestion=suggestion, actor=RESEARCHER.user_id
    )

    # 人工处置：接受建议
    assert saved.suggestion_id is not None
    updated = status_service.apply_decision(
        uow,
        thesis=uow.thesis.get(THESIS_ID),
        hypotheses=uow.thesis.list_hypotheses(THESIS_ID),
        suggestion_id=saved.suggestion_id,
        action=status_service.ACCEPT,
        actor=RESEARCHER.user_id,
        reason="盈利质量假设被削弱，接受建议并安排复核",
    )

    confirmed = [
        e
        for e in uow.evidence.list_for_thesis(THESIS_ID)
        if e.confirmation_status is ConfirmationStatus.CONFIRMED
    ]

    return Result(
        documents=len(documents),
        segments=segments_total,
        events=len(events),
        candidates=len(change.candidates),
        confirmed=len(confirmed),
        suggestion_status=suggestion.suggested_status.value,
        suggestion_reasons=list(suggestion.reasons),
        final_status=updated.status.value,
        versions=len(uow.versions.list_for_thesis(THESIS_ID)),
        audit_actions=sorted(set(uow.audit.actions())),
        invalidation_note=next(
            (r for r in suggestion.reasons if "失效条件" in r or "不判定失效" in r), ""
        ),
        metric_findings=_metric_findings(uow),
    )


def _metric_findings(uow: Any) -> list[dict[str, str]]:
    """逐条假设列出指标判定结果，供人工核对。"""
    findings: list[dict[str, str]] = []
    thesis = uow.thesis.get(THESIS_ID)
    for hypothesis in uow.thesis.list_hypotheses(THESIS_ID):
        for mapping in uow.thesis.list_mappings(hypothesis.hypothesis_id):
            observations = uow.observations.list_for_metric(SECURITY_ID, mapping.metric_id)
            in_window = [o for o in observations if o.observation_date >= thesis.established_on]
            excluded = [o for o in observations if o.observation_date < thesis.established_on]
            latest = max(in_window, key=lambda o: o.observation_date) if in_window else None
            findings.append(
                {
                    "hypothesis": hypothesis.hypothesis_id,
                    "metric": mapping.metric_id,
                    "threshold": str(mapping.invalidation_threshold),
                    "latest_period": latest.period if latest else "无窗口内数据",
                    "latest_value": str(latest.actual_value) if latest else "-",
                    "excluded": ",".join(o.period for o in excluded) or "无",
                    "required_periods": str(mapping.invalidation_consecutive_periods),
                }
            )
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    result = run()

    if args.json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return

    print("=" * 68)
    print("真实案例 MVP 闭环验证：阳光电源（300274.SZ）储能业务")
    print("=" * 68)
    print(f"解析文档     {result.documents} 份，切片 {result.segments} 段")
    print(f"事件         {result.events} 条")
    print(f"候选证据     {result.candidates} 条（全部待确认）")
    print(f"人工确认     {result.confirmed} 条")
    print()
    print("指标判定：")
    for item in result.metric_findings:
        print(
            f"  {item['hypothesis']}  {item['metric']}"
            f"  阈值 {item['threshold']}"
            f"  最近 {item['latest_period']}={item['latest_value']}"
            f"  要求连续 {item['required_periods']} 期"
            f"  裁剪排除 {item['excluded']}"
        )
    print()
    print(f"状态建议     {result.suggestion_status}")
    for reason in result.suggestion_reasons:
        print(f"  - {reason}")
    print()
    print(f"人工处置后   {result.final_status}")
    print(f"版本快照     {result.versions} 个")
    print(f"审计动作     {'、'.join(result.audit_actions)}")
    print()
    print("本系统输出候选信号与状态建议，不构成投资建议，不产生交易指令。")


if __name__ == "__main__":
    main()
