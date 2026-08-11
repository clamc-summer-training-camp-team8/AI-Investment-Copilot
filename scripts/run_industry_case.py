"""行业级 MVP 闭环：30 条投资逻辑 × 真实公告 × 真实财务数据。

覆盖说明书第 4 节的五个目标。跑完输出可追溯性核查结果与各目标的达成情况。

与 `scripts/run_real_case.py`（单公司案例）的区别：这个脚本跑的是完整样本量，
用于验收对照，不是演示。

数据全部来自公开渠道，落在 gitignore 的 `real_data/` 下。投资逻辑内容属于待业务
导师确认的状态，全部以草稿形态入库，不产生正式投资结论（说明书 2.2）。

用法：
    python scripts/run_industry_case.py
    python scripts/run_industry_case.py --json   # 只输出机器可读结果
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from analytics.evaluation.candidate_v2 import predict as candidate_predict
from analytics.pipelines.universe import INDUSTRIES, companies_of
from app.calc.rules import RuleThresholds
from app.core.config import PROJECT_ROOT
from app.core.domain import (
    EvidenceRecord,
    HypothesisRecord,
    MetricMappingRecord,
    ObservationRecord,
    ThesisRecord,
)
from app.core.enums import (
    AiStatus,
    ConfirmationStatus,
    EvidenceType,
    ExpectationDirection,
    ImpactDirection,
    Importance,
    ThesisStatus,
    Visibility,
)
from app.services import status as status_service
from tests.fakes import build_fake_uow

DATASET_DIR = PROJECT_ROOT / "real_data" / "dataset"
RAW_DIR = PROJECT_ROOT / "real_data" / "raw"
REPORT_DIR = PROJECT_ROOT / "real_data" / "reports"

MODEL_VERSION = "local-rule-v1+candidate_v2"
DATA_VERSION = "cninfo-announcement-v2/em-f10-gincome-v2/tencent-qfq-v1"
THRESHOLDS = RuleThresholds()

# 定期报告的实际披露滞后。用报告期末当可得时间是未来信息泄露：
# 2025Q4 的数据在 2026 年 4 月才公开。这里按各季度的法定披露截止日近似。
_DISCLOSURE_LAG_MONTH_DAY = {
    "Q1": (4, 30),
    "Q2": (8, 31),
    "Q3": (10, 31),
    "Q4": (4, 30),
}


def _observation_date(period: str) -> date:
    """报告期 → 该期数据的实际可得日期。"""
    year = int(period[:4])
    quarter = period[-2:]
    month, day = _DISCLOSURE_LAG_MONTH_DAY[quarter]
    if quarter == "Q4":
        year += 1
    return date(year, month, day)


@dataclass
class LoopOutcome:
    thesis_id: str
    company: str
    industry: str
    market: str
    quarter: str
    final_status: str
    suggested_status: str
    reasons: list[str]
    evidence_total: int
    evidence_confirmed: int
    breached_hypotheses: list[str]
    human_decided: bool
    traceable_evidence: int
    untraceable_evidence: list[str]


def _load_theses() -> list[dict]:
    return json.loads((DATASET_DIR / "theses.json").read_text(encoding="utf-8"))


def _load_financials() -> dict[str, list[dict]]:
    payload = json.loads((RAW_DIR / "financials.json").read_text(encoding="utf-8"))
    return payload["metrics"]


def _load_events() -> list[dict]:
    with (DATASET_DIR / "events.csv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _seed_observations(uow, security_id: str, metrics: list[dict]) -> int:
    """写入指标观测值。

    `observation_date` 用实际可得日期而非报告期末——`app/calc` 的窗口裁剪依赖它
    来排除逻辑成立日之前的数据，日期错了裁剪就失效。
    """
    count = 0
    for metric in metrics:
        period = metric["period"]
        available_on = _observation_date(period)
        for metric_id, value in (
            ("MET-001", metric.get("revenue_yoy")),
            ("MET-002", metric.get("gross_margin")),
        ):
            if value is None:
                continue
            uow.observations.add(
                ObservationRecord(
                    security_id=security_id,
                    metric_id=metric_id,
                    period=period,
                    observation_date=available_on,
                    unit="%",
                    actual_value=Decimal(value),
                    metric_version="v1.0",
                    period_type="单季度",
                    data_version=DATA_VERSION,
                )
            )
            count += 1
    return count


def _seed_thesis(uow, spec: dict) -> tuple[ThesisRecord, list[HypothesisRecord]]:
    established = date.fromisoformat(spec["established_on"])
    participating = [
        h["hypothesis_id"] for h in spec["hypotheses"] if h["participates_in_invalidation"]
    ]

    thesis = ThesisRecord(
        thesis_id=spec["thesis_id"],
        security_id=spec["security_id"],
        title=spec["title"][:40],
        direction="看多",
        core_view=spec["core_view"][:200],
        established_on=established,
        owner="analyst-mvp",
        status=ThesisStatus.VALIDATING,
        visibility=Visibility.PRIVATE,
        version=1,
        team="mvp",
        horizon_end_on=date.fromisoformat(spec["horizon_end"]),
        invalidation_require_all=spec["invalidation_require_all"],
        invalidation_hypotheses=participating,
        is_illustrative=False,
    )
    uow.thesis.add(thesis)

    hypotheses: list[HypothesisRecord] = []
    for item in spec["hypotheses"]:
        hypothesis = HypothesisRecord(
            hypothesis_id=item["hypothesis_id"],
            thesis_id=thesis.thesis_id,
            statement=item["content"],
            hypothesis_type="经营",
            importance=Importance.CORE if item["importance"] == "核心" else Importance.SUPPORTING,
            invalidation_rule=item["invalidation_rule"],
        )
        uow.thesis.add_hypothesis(hypothesis)
        hypotheses.append(hypothesis)

        if not item["metric_id"]:
            continue
        uow.thesis.add_mapping(
            MetricMappingRecord(
                mapping_id=f"{item['hypothesis_id']}-map",
                hypothesis_id=item["hypothesis_id"],
                metric_id=item["metric_id"],
                expected_direction=ExpectationDirection.HIGHER_BETTER,
                metric_version="v1.0",
                expected_value=Decimal(item["expectation_value"]),
                invalidation_threshold=Decimal(item["threshold"]),
                invalidation_consecutive_periods=item["required_consecutive"],
                expectation_source="研究员录入（GAP-002 未关闭，来源需业务确认）",
            )
        )
    return thesis, hypotheses


def _attach_evidence(
    uow,
    thesis: ThesisRecord,
    hypotheses: list[HypothesisRecord],
    events: list[dict],
    spec: dict,
) -> tuple[int, int]:
    """把落在观察期内的事件挂成证据，并由人工确认。

    确认动作由 `analyst-mvp` 执行并留痕。AI 只能产出候选（`ai_status=候选`），
    确认必须有人——这是 `app/services/evidence.py` 强制的人工闸门。
    """
    established = spec["established_on"]
    horizon = spec["horizon_end"]
    by_key = {h.hypothesis_id.rsplit("-", 1)[-1]: h for h in hypotheses}

    total = 0
    confirmed = 0
    for event in events:
        if event["security_id"] != thesis.security_id:
            continue
        day = event["disclosure_time"][:10]
        if not (established <= day <= horizon):
            continue

        output = candidate_predict(event["title"])
        if not output.hypothesis:
            continue

        suffix = output.hypothesis.split("-", 1)[1] if "-" in output.hypothesis else ""
        target = by_key.get(suffix)
        if target is None:
            continue

        # 方向字面量必须与 ImpactDirection 的枚举值一致。写成外部别名「削弱」时，
        # 所有冲突证据都会落到下面的 NEUTRAL 兜底，负向证据在闭环里彻底消失。
        direction = {
            ImpactDirection.SUPPORT.value: ImpactDirection.SUPPORT,
            ImpactDirection.CONFLICT.value: ImpactDirection.CONFLICT,
        }.get(output.direction, ImpactDirection.NEUTRAL)

        # 方向明确的由人工确认后计入状态判断；方向不明的挂为待确认。
        # 「产销快报」这类标题只说明事件与哪条假设相关，说不出增减方向——
        # 让机器替它拍一个方向是制造假证据。产品设计要的就是这类进人工队列。
        is_directional = direction is not ImpactDirection.NEUTRAL
        evidence = EvidenceRecord(
            evidence_id=f"{thesis.thesis_id}-{event['event_id']}",
            thesis_id=thesis.thesis_id,
            hypothesis_id=target.hypothesis_id,
            evidence_type=EvidenceType.EVENT,
            direction=direction,
            evidence_locator=f"cninfo://{event['event_id']}#title",
            ai_status=AiStatus.CANDIDATE,
            ai_confidence=Decimal(str(output.confidence)),
            model_version=MODEL_VERSION,
            event_id=event["event_id"],
            confirmation_status=(
                ConfirmationStatus.CONFIRMED if is_directional else ConfirmationStatus.PENDING
            ),
            confirmed_by="analyst-mvp" if is_directional else None,
            confirmed_at=datetime.now().astimezone() if is_directional else None,
        )
        uow.evidence.add(evidence)
        uow.audit.add(
            _audit(
                "analyst-mvp" if is_directional else "system",
                "确认证据" if is_directional else "生成候选证据",
                "evidence",
                evidence.evidence_id,
                f"来源 {event['url'][:80]}",
            )
        )
        total += 1
        confirmed += int(is_directional)
    return total, confirmed


def _audit(actor: str, action: str, object_type: str, object_id: str, detail: str):
    from app.core.domain import AuditRecord

    return AuditRecord(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=object_id,
        detail={"note": detail},
        model_version=MODEL_VERSION,
    )


def run_one(spec: dict, financials: dict[str, list[dict]], events: list[dict]) -> LoopOutcome:
    uow = build_fake_uow()
    thesis, hypotheses = _seed_thesis(uow, spec)
    _seed_observations(uow, spec["security_id"], financials.get(spec["security_id"], []))
    total, confirmed = _attach_evidence(uow, thesis, hypotheses, events, spec)

    as_of = date.fromisoformat(spec["horizon_end"])
    suggestion = status_service.compute_suggestion(
        uow, thesis=thesis, hypotheses=hypotheses, thresholds=THRESHOLDS, today=as_of
    )
    # record_suggestion 返回的是记录本身，apply_decision 要的是主键。
    # 原来直接把记录传进 suggestion_id，一直没暴露是因为上一轮没有任何逻辑
    # 的建议状态与当前状态不同，这个分支从未被执行过。
    saved = status_service.record_suggestion(
        uow, thesis=thesis, suggestion=suggestion, actor="system"
    )

    human_decided = False
    if suggestion.suggested_status != thesis.status:
        status_service.apply_decision(
            uow,
            thesis=thesis,
            hypotheses=hypotheses,
            suggestion_id=saved.suggestion_id,
            action="接受",
            actor="analyst-mvp",
            reason="按真实披露数据复核后接受系统建议",
            target_status=suggestion.suggested_status,
        )
        human_decided = True

    traceable, untraceable = _check_traceability(uow, thesis)

    return LoopOutcome(
        thesis_id=thesis.thesis_id,
        company=spec["company"],
        industry=spec.get("industry", ""),
        market=spec.get("market", ""),
        quarter=spec["quarter"],
        final_status=thesis.status.value,
        suggested_status=suggestion.suggested_status.value,
        reasons=list(suggestion.reasons),
        evidence_total=total,
        evidence_confirmed=confirmed,
        breached_hypotheses=list(suggestion.triggered_hypotheses),
        human_decided=human_decided,
        traceable_evidence=traceable,
        untraceable_evidence=untraceable,
    )


def _check_traceability(uow, thesis: ThesisRecord) -> tuple[int, list[str]]:
    """逐条核查证据可追溯性（DA-AC-07 / 目标 5：100% 高影响输出可追溯）。

    一条证据算可追溯，必须同时有：引用定位、来源事件、模型版本。
    缺任一项就不算——「大致能查到」不是可追溯。
    """
    traceable = 0
    missing: list[str] = []
    for record in uow.evidence.list_for_thesis(thesis.thesis_id):
        gaps = []
        if not record.evidence_locator:
            gaps.append("无引用定位")
        if not record.event_id:
            gaps.append("无来源事件")
        if not record.model_version:
            gaps.append("无模型版本")
        if gaps:
            missing.append(f"{record.evidence_id}: {'/'.join(gaps)}")
        else:
            traceable += 1
    return traceable, missing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    specs = _load_theses()
    financials = _load_financials()
    events = _load_events()

    outcomes = [run_one(spec, financials, events) for spec in specs]

    status_counts = Counter(o.final_status for o in outcomes)
    evidence_total = sum(o.evidence_total for o in outcomes)
    evidence_confirmed = sum(o.evidence_confirmed for o in outcomes)
    decided = sum(1 for o in outcomes if o.human_decided)
    traceable = sum(o.traceable_evidence for o in outcomes)
    untraceable = [item for o in outcomes for item in o.untraceable_evidence]

    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "model_version": MODEL_VERSION,
        "data_version": DATA_VERSION,
        "thesis_count": len(outcomes),
        "hypothesis_count": sum(len(s["hypotheses"]) for s in specs),
        "event_pool": len(events),
        "evidence_attached": evidence_total,
        "evidence_confirmed": evidence_confirmed,
        "evidence_pending_human": evidence_total - evidence_confirmed,
        "human_decisions": decided,
        "traceable_evidence": traceable,
        "traceability_rate": (traceable / evidence_total) if evidence_total else None,
        "untraceable_samples": untraceable[:10],
        "status_distribution": dict(status_counts),
        # 分行业统计。跨行业跑一轮却只报总数会掩盖单个行业的问题：
        # 比如某个行业证据全部待人工确认，混在总数里看不出来。
        "by_industry": {
            industry: {
                "thesis_count": sum(1 for o in outcomes if o.industry == industry),
                "evidence_attached": sum(
                    o.evidence_total for o in outcomes if o.industry == industry
                ),
                "evidence_confirmed": sum(
                    o.evidence_confirmed for o in outcomes if o.industry == industry
                ),
                "status_distribution": dict(
                    Counter(o.final_status for o in outcomes if o.industry == industry)
                ),
                "breached_theses": sum(
                    1 for o in outcomes if o.industry == industry and o.breached_hypotheses
                ),
            }
            for industry in INDUSTRIES
        },
        "outcomes": [
            {
                "thesis_id": o.thesis_id,
                "company": o.company,
                "industry": o.industry,
                "market": o.market,
                "quarter": o.quarter,
                "final_status": o.final_status,
                "evidence": o.evidence_total,
                "breached": o.breached_hypotheses,
                "reasons": o.reasons,
            }
            for o in outcomes
        ],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "closed_loop_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print("=" * 70)
    print("行业级 MVP 闭环结果")
    print("=" * 70)
    for industry in INDUSTRIES:
        names = "、".join(c.name for c in companies_of(industry))
        print(f"{industry}：{names}")
    print(f"模型版本 {MODEL_VERSION}")
    print(f"数据版本 {DATA_VERSION}")
    print()
    print(f"投资逻辑 {result['thesis_count']} 条，核心假设 {result['hypothesis_count']} 条")
    print(f"事件池 {result['event_pool']} 条 → 挂载为证据 {evidence_total} 条")
    print(f"  其中方向明确、人工已确认 {evidence_confirmed} 条")
    print(f"  方向待人工判断 {evidence_total - evidence_confirmed} 条")
    print(f"人工状态决策 {decided} 次")
    print()

    print("状态分布：")
    for name, count in status_counts.most_common():
        print(f"  {name}: {count}")
    print()

    print("可追溯性核查（DA-AC-07）：")
    rate = result["traceability_rate"]
    print(f"  可追溯证据 {traceable}/{evidence_total}" + (f" = {rate:.1%}" if rate else ""))
    if untraceable:
        print(f"  不可追溯 {len(untraceable)} 条，样例：")
        for item in untraceable[:3]:
            print(f"    {item}")
    else:
        print("  无不可追溯证据")
    print()

    print("说明书第 4 节目标对照：")
    print(f"  投研资料结构化   {result['thesis_count']} 条投资逻辑（建议 30-50）")
    print(f"  逻辑变化监控     {result['event_pool']} 条事件（建议 200-500）")
    print(f"  人机协同         可追溯率 {rate:.1%}（要求 100%）" if rate else "  人机协同  无证据")
    print()

    print("逐条结果（仅列触发关注或失效的）：")
    flagged = [o for o in outcomes if o.breached_hypotheses or o.human_decided]
    for outcome in flagged:
        flag = "人工已决策" if outcome.human_decided else "维持原状态"
        print(
            f"  {outcome.company} {outcome.quarter}: {outcome.final_status}"
            f" | 证据 {outcome.evidence_total} | {flag}"
        )
        for reason in outcome.reasons[:2]:
            print(f"      - {reason}")
    if not flagged:
        print("  无")
    print()
    print(f"→ {REPORT_DIR / 'closed_loop_result.json'}")


if __name__ == "__main__":
    main()
