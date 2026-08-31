"""登记默认冻结行情，并把数据库中真实人工确认的关系冻结为研究信号集。"""

from decimal import Decimal

from sqlalchemy import select

from app.db.models.core import Evidence, EvidenceRelation
from app.db.repositories import build_uow
from app.db.session import session_scope
from app.services.quant import FrozenSignalInput, freeze_signal_set, register_default_market_dataset


def main() -> None:
    with session_scope() as session:
        uow = build_uow(session)
        record = register_default_market_dataset(uow, frozen_by="p2-bootstrap")
        rows = session.execute(
            select(EvidenceRelation, Evidence)
            .join(Evidence, Evidence.evidence_id == EvidenceRelation.evidence_id)
            .where(
                EvidenceRelation.status == "已确认",
                EvidenceRelation.reviewed_at.is_not(None),
                Evidence.disclosed_at.is_not(None),
                Evidence.security_id.in_(record.securities),
            )
            .order_by(EvidenceRelation.reviewed_at, EvidenceRelation.relation_id)
        ).all()
        signals = [
            FrozenSignalInput(
                signal_id=f"QSG-{relation.relation_id}",
                security_id=str(evidence.security_id),
                disclosed_at=evidence.disclosed_at,
                generated_at=relation.reviewed_at,
                direction=relation.direction,
                strength=relation.strength if relation.strength in {"高", "中", "低"} else "中",
                confidence=Decimal(1),
                confirmation_status="已确认",
                source_evidence_id=evidence.evidence_id,
                source_relation_id=relation.relation_id,
            )
            for relation, evidence in rows
            if evidence.security_id is not None
            and evidence.disclosed_at is not None
            and relation.reviewed_at is not None
            and relation.direction in {"支持", "冲突", "中性"}
        ]
        signal_set = (
            freeze_signal_set(
                uow,
                name="人工确认关系研究信号",
                version="confirmed-relations-20260830-v1",
                signals=signals,
                frozen_by="p2-bootstrap",
            )
            if signals
            else None
        )
    print(f"量化行情已登记: {record.dataset_id} {record.manifest_sha256}")
    if signal_set is None:
        print("当前没有满足披露时间与人工确认时间要求的关系，未生成信号集")
    else:
        print(f"人工确认信号已冻结: {signal_set.signal_set_id} count={signal_set.signal_count}")


if __name__ == "__main__":
    main()
