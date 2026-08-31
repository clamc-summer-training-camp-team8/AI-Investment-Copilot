"""按显式行情版本和时间截面冻结人工确认关系信号集，不切换默认行情。"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.core.domain import UnitOfWork
from app.core.timeutil import next_observable_day, to_business
from app.db.models.core import Evidence, EvidenceRelation
from app.db.repositories import build_uow
from app.db.session import session_scope
from app.services.quant import FrozenSignalInput, freeze_signal_set


@dataclass(frozen=True)
class ConfirmedRelationSignalSource:
    relation_id: str
    evidence_id: str
    security_id: str
    disclosed_at: datetime
    reviewed_at: datetime
    direction: str
    strength: str | None


@dataclass(frozen=True)
class ConfirmedSignalSetPlan:
    market_dataset_id: str
    market_coverage_end: str
    first_eligible_market_date: str
    version: str
    signals: tuple[FrozenSignalInput, ...]


def plan_confirmed_signal_set(
    uow: UnitOfWork,
    *,
    sources: list[ConfirmedRelationSignalSource],
    market_dataset_id: str,
    version: str,
    as_of: datetime,
    expected_signal_count: int,
    required_relation_ids: frozenset[str],
) -> ConfirmedSignalSetPlan:
    if as_of.tzinfo is None:
        raise ValueError("as-of 必须包含时区")
    if expected_signal_count < 1:
        raise ValueError("expected-signal-count 必须大于零")
    dataset = uow.quant.get_market_dataset(market_dataset_id)
    if dataset is None or dataset.status != "frozen":
        raise ValueError("指定行情数据集不存在或尚未冻结")

    cutoff = to_business(as_of)
    eligible = [item for item in sources if to_business(item.reviewed_at) <= cutoff]
    eligible.sort(key=lambda item: (to_business(item.reviewed_at), item.relation_id))
    present_relations = {item.relation_id for item in eligible}
    missing_relations = sorted(required_relation_ids - present_relations)
    if missing_relations:
        raise ValueError(f"必要人工确认关系未进入信号集: {missing_relations}")
    if len(eligible) != expected_signal_count:
        raise ValueError(
            f"人工确认信号数量不符: expected={expected_signal_count} actual={len(eligible)}"
        )

    signals: list[FrozenSignalInput] = []
    for item in eligible:
        if item.security_id not in dataset.securities:
            raise ValueError(f"{item.relation_id}: 证券不在指定行情数据集中")
        if to_business(item.reviewed_at) < to_business(item.disclosed_at):
            raise ValueError(f"{item.relation_id}: 人工确认时间早于披露时间")
        if item.direction not in {"支持", "冲突", "中性"}:
            raise ValueError(f"{item.relation_id}: 方向不能进入量化信号")
        signals.append(
            FrozenSignalInput(
                signal_id=f"QSG-{item.relation_id}",
                security_id=item.security_id,
                disclosed_at=item.disclosed_at,
                generated_at=item.reviewed_at,
                direction=item.direction,
                strength=item.strength if item.strength in {"高", "中", "低"} else "中",
                confidence=Decimal(1),
                confirmation_status="已确认",
                source_evidence_id=item.evidence_id,
                source_relation_id=item.relation_id,
            )
        )

    first_eligible_market_date = next_observable_day(max(item.generated_at for item in signals))
    if dataset.coverage_end < first_eligible_market_date:
        raise ValueError(
            "行情覆盖不足：最新人工确认后的首个可观察日期为 "
            f"{first_eligible_market_date.isoformat()}，但数据集只到 {dataset.coverage_end.isoformat()}"
        )
    return ConfirmedSignalSetPlan(
        market_dataset_id=market_dataset_id,
        market_coverage_end=dataset.coverage_end.isoformat(),
        first_eligible_market_date=first_eligible_market_date.isoformat(),
        version=version,
        signals=tuple(signals),
    )


def _load_sources(session, *, market_securities: list[str]) -> list[ConfirmedRelationSignalSource]:
    rows = session.execute(
        select(EvidenceRelation, Evidence)
        .join(Evidence, Evidence.evidence_id == EvidenceRelation.evidence_id)
        .where(
            EvidenceRelation.status == "已确认",
            EvidenceRelation.reviewed_at.is_not(None),
            Evidence.disclosed_at.is_not(None),
            Evidence.security_id.in_(market_securities),
        )
        .order_by(EvidenceRelation.reviewed_at, EvidenceRelation.relation_id)
    ).all()
    return [
        ConfirmedRelationSignalSource(
            relation_id=relation.relation_id,
            evidence_id=evidence.evidence_id,
            security_id=str(evidence.security_id),
            disclosed_at=evidence.disclosed_at,
            reviewed_at=relation.reviewed_at,
            direction=relation.direction,
            strength=relation.strength,
        )
        for relation, evidence in rows
        if evidence.security_id is not None
        and evidence.disclosed_at is not None
        and relation.reviewed_at is not None
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-dataset-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--name", default="人工确认关系研究信号")
    parser.add_argument("--as-of", required=True, help="带时区 ISO 8601 截面")
    parser.add_argument("--expected-signal-count", required=True, type=int)
    parser.add_argument("--required-relation-id", action="append", default=[])
    parser.add_argument("--frozen-by", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    as_of = datetime.fromisoformat(args.as_of)
    with session_scope() as session:
        uow = build_uow(session)
        dataset = uow.quant.get_market_dataset(args.market_dataset_id)
        if dataset is None:
            raise SystemExit("指定行情数据集不存在")
        try:
            plan = plan_confirmed_signal_set(
                uow,
                sources=_load_sources(session, market_securities=dataset.securities),
                market_dataset_id=args.market_dataset_id,
                version=args.version,
                as_of=as_of,
                expected_signal_count=args.expected_signal_count,
                required_relation_ids=frozenset(args.required_relation_id),
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        record = None
        existing_signal_set_ids = {item.signal_set_id for item in uow.quant.list_signal_sets()}
        if args.apply:
            record = freeze_signal_set(
                uow,
                name=args.name,
                version=args.version,
                signals=list(plan.signals),
                frozen_by=args.frozen_by,
            )
        output = {
            "mode": "apply" if args.apply else "dry-run",
            "market_dataset_id": plan.market_dataset_id,
            "market_coverage_end": plan.market_coverage_end,
            "first_eligible_market_date": plan.first_eligible_market_date,
            "version": plan.version,
            "signal_count": len(plan.signals),
            "signals": [asdict(item) for item in plan.signals],
            "signal_set_id": record.signal_set_id if record else None,
            "database_write_performed": bool(
                args.apply and record and record.signal_set_id not in existing_signal_set_ids
            ),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
