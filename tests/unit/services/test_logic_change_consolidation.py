from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.ai.gateway import Gateway
from app.core.config import Settings
from app.core.domain import EvidenceRecord, HypothesisRecord, ThesisRecord
from app.core.enums import ConfirmationStatus, ImpactDirection, Importance, ThesisStatus
from app.services.logic_change_consolidation import consolidate_daily_logic_change
from tests.fakes import build_fake_uow

TZ = ZoneInfo("Asia/Shanghai")


@pytest.mark.asyncio
async def test_daily_consolidation_reads_all_same_day_candidates_and_upserts_one_digest() -> None:
    uow = build_fake_uow()
    uow.thesis.add(
        ThesisRecord(
            thesis_id="THS-1",
            security_id="000001",
            title="收入与利润改善",
            direction="看多",
            core_view="订单增长转化为收入，并带动盈利改善。",
            established_on=date(2026, 1, 1),
            owner="researcher-1",
            status=ThesisStatus.VALIDATING,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="HYP-1",
            thesis_id="THS-1",
            statement="订单增长支撑收入提升",
            hypothesis_type="经营",
            importance=Importance.CORE,
        )
    )
    uow.thesis.add_hypothesis(
        HypothesisRecord(
            hypothesis_id="HYP-2",
            thesis_id="THS-1",
            statement="毛利率改善支撑盈利",
            hypothesis_type="盈利",
            importance=Importance.CORE,
        )
    )
    for evidence_id, hypothesis_id, direction, fact in (
        ("EVD-1", "HYP-1", ImpactDirection.SUPPORT, "新签订单同比增长。"),
        ("EVD-2", "HYP-2", ImpactDirection.CONFLICT, "产品降价使毛利率承压。"),
    ):
        uow.evidence.add(
            EvidenceRecord(
                evidence_id=evidence_id,
                thesis_id="THS-1",
                hypothesis_id=hypothesis_id,
                evidence_type="事件",
                direction=direction,
                evidence_locator=f"DOC-{evidence_id}#paragraph-1",
                security_id="000001",
                fact_excerpt=fact,
                source_document_id=f"DOC-{evidence_id}",
                source_document_title="当日研究资料",
                disclosed_at=datetime(2026, 8, 31, 9, tzinfo=TZ),
                ingested_at=datetime(2026, 8, 31, 10, tzinfo=TZ),
                ai_confidence=Decimal("0.80"),
                confirmation_status=ConfirmationStatus.PENDING,
            )
        )

    result = await consolidate_daily_logic_change(
        uow,
        gateway=Gateway.build(Settings(_env_file=None, llm_provider="local")),
        security_id="000001",
        thesis_id="THS-1",
        as_of=date(2026, 8, 31),
        actor_id="researcher-1",
    )

    assert result.candidate_count == 2
    assert result.digest_id
    digest = uow.logic_change_digests.get_for_scope(
        security_id="000001", thesis_id="THS-1", business_date=date(2026, 8, 31)
    )
    assert digest is not None
    assert digest.overall_direction == "混合"
    assert digest.candidate_count == 2
    assert set(digest.citations) == {"EVD-1", "EVD-2"}
    assert digest.confirmation_status is ConfirmationStatus.PENDING

    # 同一天新资料到达后覆盖同一份待确认草稿，不额外生成难维护的主题卡片。
    repeated = await consolidate_daily_logic_change(
        uow,
        gateway=Gateway.build(Settings(_env_file=None, llm_provider="local")),
        security_id="000001",
        thesis_id="THS-1",
        as_of=date(2026, 8, 31),
        actor_id="researcher-1",
    )
    assert repeated.digest_id == result.digest_id
    assert len(uow.logic_change_digests.items) == 1
