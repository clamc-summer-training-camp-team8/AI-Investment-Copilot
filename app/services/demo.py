"""中芯国际 2023 年报重大风险真实 Demo 编排与只读投影。"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.services.errors import NotVisible, ValidationFailed
from app.services.permission import Actor, ensure_thesis_visible

DEMO_CASE_ID = "smic-2023-risk"
DEMO_THESIS_ID = "THS-688981-2023FY"
DEMO_SECURITY_ID = "688981"
MATERIAL_HASH = "c26951660ae179cd1880b509d8cf5bbd4d55eb4a30254fc183d598149d815c8c"
SOURCE_URL = "https://www.smics.com/uploads/66152426/688981.pdf"
DISCLOSED_AT = datetime(2024, 3, 29)

DOCUMENT_ID = "DOC-688981-2023FY"
EVIDENCE_ID = "EVD-688981-2023FY-RISK"
RELATION_ID = "REL-688981-2023FY-DEMAND"
HYPOTHESIS_IDS = {
    "demand": f"{DEMO_THESIS_ID}-H1-DEMAND",
    "profit": f"{DEMO_THESIS_ID}-H2-PROFIT",
    "capacity": f"{DEMO_THESIS_ID}-H3-CAPACITY",
}
METRIC_IDS = {
    "demand": "MET-SMIC-ANNUAL-REVENUE-YOY",
    "profit": "MET-SMIC-ANNUAL-GROSS-MARGIN",
    "capacity": "MET-SMIC-CAPACITY-UTILIZATION",
}
OBSERVATIONS = {
    "demand": Decimal("-8.6"),
    "profit": Decimal("21.9"),
    "capacity": Decimal("75.0"),
}
THRESHOLDS = {
    "demand": Decimal("0"),
    "profit": Decimal("25"),
    "capacity": Decimal("80"),
}
METRIC_NAMES = {
    "demand": "营业收入同比",
    "profit": "毛利率",
    "capacity": "平均产能利用率",
}
SEGMENTS = (
    (
        f"{DOCUMENT_ID}#paragraph-1",
        1,
        6,
        (
            "公司全年销售收入人民币453亿元，调整波动幅度好于行业平均水平，毛利率为22%，"
            "年平均产能利用率为75%，基本符合年初指引。"
        ),
    ),
    (
        f"{DOCUMENT_ID}#paragraph-2",
        2,
        9,
        (
            "营业收入：2023年45,250,425千元，2022年49,516,084千元，"
            "本期比上年同期增减-8.6%；毛利率：2023年21.9%，2022年38.3%，"
            "减少16.4个百分点。"
        ),
    ),
    (
        f"{DOCUMENT_ID}#paragraph-3",
        3,
        10,
        (
            "本年营业收入、归属于上市公司股东的净利润、毛利率以及净利率下降，主要是由于："
            "过去一年，半导体行业处于周期底部，全球市场需求疲软，行业库存较高，去库存缓慢，"
            "且同业竞争激烈。受此影响，集团平均产能利用率降低，晶圆销售数量减少，产品组合变动。"
            "此外，集团处于高投入期，折旧较2022年增加。"
        ),
    ),
)

MATERIALS: dict[str, dict[str, str]] = {
    MATERIAL_HASH: {
        "document_id": DOCUMENT_ID,
        "evidence_id": EVIDENCE_ID,
        "relation_id": RELATION_ID,
        "label": "中芯国际2023年年度报告",
        "direction": "冲突",
    }
}


class DemoFileMismatch(ValidationFailed):
    """上传内容不是登记的固定公开资料。"""


def record_timeline(
    audit_repo: Any,
    *,
    thesis_id: str,
    actor: str,
    action: str,
    dimension: str,
    event_type: str,
    actor_type: str,
    summary: str,
    related_object_type: str | None = None,
    related_object_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    detail_url: str | None = None,
) -> None:
    """通过既有审计端口写结构化时间线，保持与业务事务一致。"""
    from app.services import audit

    audit.record(
        audit_repo,
        actor=actor,
        action=action,
        object_type="thesis_timeline",
        object_id=thesis_id,
        detail={
            "dimension": dimension,
            "event_type": event_type,
            "actor_type": actor_type,
            "summary": summary,
            "related_object_type": related_object_type,
            "related_object_id": related_object_id,
            "before": before,
            "after": after,
            "reason": reason,
            "detail_url": detail_url,
        },
    )


@contextmanager
def _session_scope() -> Iterator[Any]:
    # 延迟导入保持 services 层纯函数测试不因模块导入而连接数据库。
    from app.db.session import session_scope

    with session_scope() as session:
        yield session


def _visible_thesis(session: Any, thesis_id: str, actor: Actor, *, owner: bool = False) -> Any:
    from app.db.models.core import Thesis

    thesis = session.get(Thesis, thesis_id)
    if thesis is None:
        raise NotVisible(f"逻辑 {thesis_id} 不存在或无访问权限")
    ensure_thesis_visible(
        actor,
        thesis_id=thesis.thesis_id,
        owner=thesis.owner,
        visibility=thesis.visibility,
        team=thesis.team,
    )
    if owner and thesis.owner != actor.user_id:
        raise PermissionError("仅投资逻辑负责人可执行此操作")
    return thesis


def _timeline(
    session: Any,
    *,
    thesis_id: str,
    actor: str,
    action: str,
    dimension: str,
    event_type: str,
    actor_type: str,
    summary: str,
    related_object_type: str | None = None,
    related_object_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    detail_url: str | None = None,
) -> None:
    from app.db.models.governance import AuditLog

    session.add(
        AuditLog(
            actor=actor,
            action=action,
            object_type="thesis_timeline",
            object_id=thesis_id,
            detail={
                "dimension": dimension,
                "event_type": event_type,
                "actor_type": actor_type,
                "summary": summary,
                "related_object_type": related_object_type,
                "related_object_id": related_object_id,
                "before": before,
                "after": after,
                "reason": reason,
                "detail_url": detail_url,
            },
        )
    )


def reset_demo_case() -> dict[str, Any]:
    """幂等重建历史逻辑，且只清理本 Demo 自建数据。"""
    from sqlalchemy import delete, or_, select

    from app.db.models.core import (
        Document,
        DocumentSegment,
        Evidence,
        EvidenceRelation,
        Hypothesis,
        HypothesisMetricMap,
        Metric,
        MetricObservation,
        Outcome,
        Security,
        Signal,
        Thesis,
    )
    from app.db.models.governance import (
        AuditLog,
        ReviewTask,
        StatusSuggestionLog,
        ThesisVersion,
    )
    from app.db.repositories import build_uow
    from app.services import version

    with _session_scope() as session:
        security = session.scalar(
            select(Security).where(
                or_(
                    Security.security_id == "688981",
                    Security.security_id == "688981.SH",
                    Security.ticker == "688981",
                )
            )
        )
        if security is None:
            raise ValidationFailed("证券主数据中不存在中芯国际 688981")
        security_id = security.security_id

        # 先删最深层引用，再删逻辑和上传后才会存在的文档，避免依赖数据库级联差异。
        signal_ids = select(Signal.signal_id).where(Signal.thesis_id == DEMO_THESIS_ID)
        session.execute(delete(Outcome).where(Outcome.signal_id.in_(signal_ids)))
        session.execute(delete(Signal).where(Signal.thesis_id == DEMO_THESIS_ID))
        session.execute(delete(ReviewTask).where(ReviewTask.thesis_id == DEMO_THESIS_ID))
        session.execute(
            delete(StatusSuggestionLog).where(StatusSuggestionLog.thesis_id == DEMO_THESIS_ID)
        )
        session.execute(delete(ThesisVersion).where(ThesisVersion.thesis_id == DEMO_THESIS_ID))
        session.execute(
            delete(AuditLog).where(
                (
                    (AuditLog.object_type == "thesis_timeline")
                    & (AuditLog.object_id == DEMO_THESIS_ID)
                )
                | ((AuditLog.object_type == "thesis") & (AuditLog.object_id == DEMO_THESIS_ID))
                | ((AuditLog.object_type == "evidence") & (AuditLog.object_id == EVIDENCE_ID))
                | (
                    (AuditLog.object_type == "evidence_relation")
                    & (AuditLog.object_id == RELATION_ID)
                )
            )
        )
        session.execute(
            delete(EvidenceRelation).where(
                (EvidenceRelation.thesis_id == DEMO_THESIS_ID)
                | (EvidenceRelation.evidence_id == EVIDENCE_ID)
            )
        )
        session.execute(delete(Evidence).where(Evidence.thesis_id == DEMO_THESIS_ID))
        session.execute(
            delete(MetricObservation).where(
                MetricObservation.source_document_id == DOCUMENT_ID,
                MetricObservation.data_version == MATERIAL_HASH,
            )
        )
        session.execute(
            delete(HypothesisMetricMap).where(
                HypothesisMetricMap.hypothesis_id.in_(HYPOTHESIS_IDS.values())
            )
        )
        session.execute(delete(Hypothesis).where(Hypothesis.thesis_id == DEMO_THESIS_ID))
        session.execute(delete(Thesis).where(Thesis.thesis_id == DEMO_THESIS_ID))
        session.execute(delete(DocumentSegment).where(DocumentSegment.document_id == DOCUMENT_ID))
        session.execute(delete(Document).where(Document.document_id == DOCUMENT_ID))
        session.flush()

        session.add(
            Thesis(
                thesis_id=DEMO_THESIS_ID,
                security_id=security_id,
                title="中芯国际：下行周期后的需求与产能修复",
                direction="观察",
                core_view=(
                    "半导体下行周期是暂时的，国内替代需求与产能利用率修复将支撑收入恢复"
                    "并稳定盈利能力"
                ),
                established_on=date(2023, 1, 15),
                owner="demo_owner",
                visibility="团队",
                team="研究一组",
                status="验证中",
                version=1,
                invalidation_require_all=True,
                is_illustrative=True,
            )
        )
        session.flush()

        hypothesis_specs = {
            "demand": (
                "需求复苏",
                "国内替代需求推动营业收入恢复，营业收入同比不应转负",
                "经营",
                "每个年度报告期，自首次公开披露日起观察",
                "营业收入同比低于0%即说明需求复苏未兑现；[连续1期]低于0%则该假设失效",
            ),
            "profit": (
                "盈利韧性",
                "产能利用率修复应稳定盈利能力，毛利率不低于25%",
                "盈利",
                "每个年度报告期，自首次公开披露日起观察",
                "毛利率低于25%即说明盈利韧性不足；[连续1期]低于25%则该假设失效",
            ),
            "capacity": (
                "产能消化",
                "国内替代需求应带动产能消化，平均产能利用率不低于80%",
                "经营",
                "每个年度报告期，自首次公开披露日起观察",
                "平均产能利用率低于80%即说明新增产能未被有效消化；[连续1期]低于80%则该假设失效",
            ),
        }
        for key, (
            name,
            statement,
            hypothesis_type,
            window,
            invalidation_rule,
        ) in hypothesis_specs.items():
            session.add(
                Hypothesis(
                    hypothesis_id=HYPOTHESIS_IDS[key],
                    thesis_id=DEMO_THESIS_ID,
                    name=name,
                    statement=statement,
                    hypothesis_type=hypothesis_type,
                    importance="核心",
                    observation_window=window,
                    expected_direction="不低于阈值",
                    invalidation_rule=invalidation_rule,
                    status="待验证",
                )
            )
        session.flush()

        metric_specs = {
            "demand": ("经营", "年度营业收入同比增速"),
            "profit": ("盈利", "（营业收入－营业成本）/ 营业收入"),
            "capacity": ("经营", "报告期内各季度产能利用率的平均值"),
        }
        for key, (category, definition) in metric_specs.items():
            metric = session.get(Metric, (METRIC_IDS[key], "v1.0"))
            if metric is None:
                session.add(
                    Metric(
                        metric_id=METRIC_IDS[key],
                        version="v1.0",
                        name=METRIC_NAMES[key],
                        category=category,
                        definition=definition,
                        unit="%",
                        frequency="年度",
                        period_type="年度",
                        source_id="smic-annual-report",
                        expected_direction="不低于阈值",
                        allow_qoq=False,
                        status="已确认",
                    )
                )
        session.flush()

        for key in HYPOTHESIS_IDS:
            session.add(
                HypothesisMetricMap(
                    mapping_id=f"MAP-{HYPOTHESIS_IDS[key]}",
                    hypothesis_id=HYPOTHESIS_IDS[key],
                    metric_id=METRIC_IDS[key],
                    metric_version="v1.0",
                    metric_role="同步",
                    expected_direction="不低于阈值",
                    expected_value=THRESHOLDS[key],
                    expectation_source="历史演示投资逻辑于2023-01-15设定",
                    validation_rule=f"{METRIC_NAMES[key]}不低于{THRESHOLDS[key]}%",
                    invalidation_rule=(f"[连续1期]{METRIC_NAMES[key]}低于{THRESHOLDS[key]}%则失效"),
                    invalidation_threshold=THRESHOLDS[key],
                    observation_frequency="年度",
                    confirmation_status="已确认",
                )
            )
        session.flush()
        uow = build_uow(session)
        thesis_record = uow.thesis.get(DEMO_THESIS_ID)
        if thesis_record is None:
            raise ValidationFailed("演示投资逻辑创建失败")
        version.create(
            uow.versions,
            thesis=thesis_record,
            hypotheses=uow.thesis.list_hypotheses(DEMO_THESIS_ID),
            triggered_by=version.TRIGGER_PUBLISH,
            created_by="demo_owner",
            change_reason="重建2023-01-15历史演示投资逻辑",
            changed_fields=["core_view", "hypotheses", "invalidation_rules"],
        )
        _timeline(
            session,
            thesis_id=DEMO_THESIS_ID,
            actor="demo_owner",
            action="建立演示投资逻辑",
            dimension="logic_decision",
            event_type="thesis_created",
            actor_type="human",
            summary="2023-01-15 建立中芯国际历史演示投资逻辑，初始状态为「验证中」",
            related_object_type="thesis",
            related_object_id=DEMO_THESIS_ID,
            after={"status": "验证中", "is_illustrative": True},
        )
        session.flush()

    return {
        "case": DEMO_CASE_ID,
        "thesis_id": DEMO_THESIS_ID,
        "security_id": security_id,
        "source_records_preserved": True,
        "relations_reset": 0,
        "suggestions": 0,
        "versions": 1,
        "timeline_events": 1,
    }


def upload_material(
    *,
    thesis_id: str,
    demo_case_id: str,
    filename: str,
    content: bytes,
    actor: Actor,
) -> dict[str, Any]:
    if thesis_id != DEMO_THESIS_ID or demo_case_id != DEMO_CASE_ID:
        raise DemoFileMismatch("当前流程演示仅支持中芯国际 2023 年报固定案例")
    digest = hashlib.sha256(content).hexdigest()
    material = MATERIALS.get(digest)
    if material is None:
        raise DemoFileMismatch(
            "文件不属于固定案例，请上传 real_data/demo_materials/smic_2023_annual_report.pdf"
        )

    from sqlalchemy import select

    from app.db.models.core import (
        Document,
        DocumentSegment,
        Evidence,
        EvidenceRelation,
        HypothesisMetricMap,
        MetricObservation,
    )
    from app.db.repositories import build_uow
    from app.services import status

    storage_dir = settings.storage_dir / "demo" / DEMO_CASE_ID
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_path = storage_dir / f"{digest}.pdf"
    if not stored_path.exists():
        stored_path.write_bytes(content)

    with _session_scope() as session:
        thesis = _visible_thesis(session, thesis_id, actor, owner=True)
        document = session.get(Document, material["document_id"])
        if document is not None:
            return _upload_result(material=material, duplicate=True)

        document = Document(
            document_id=DOCUMENT_ID,
            title="中芯国际集成电路制造有限公司2023年年度报告",
            source_id="smic-official",
            doc_type="年报",
            security_id=thesis.security_id,
            published_at=DISCLOSED_AT,
            content_hash=digest,
            parser_version="demo-v1",
            raw_path=str(stored_path),
            body="\n".join(segment[3] for segment in SEGMENTS),
            content_status="完整正文",
            visibility_label="公开",
            is_illustrative=False,
        )
        session.add(document)
        for locator, ordinal, page, segment_content in SEGMENTS:
            session.add(
                DocumentSegment(
                    document_id=DOCUMENT_ID,
                    locator=locator,
                    ordinal=ordinal,
                    page=page,
                    content=segment_content,
                )
            )
        evidence = Evidence(
            evidence_id=EVIDENCE_ID,
            security_id=thesis.security_id,
            thesis_id=DEMO_THESIS_ID,
            hypothesis_id=HYPOTHESIS_IDS["demand"],
            evidence_type="指标变化",
            direction="冲突",
            strength="高",
            strength_score=Decimal("0.95"),
            horizon="中期",
            is_direct=True,
            evidence_locator=SEGMENTS[1][0],
            transmission_path=(
                "行业下行与客户需求疲弱 → 收入同比转负 → 产能利用率降至75.0% → "
                "固定成本与新增折旧摊薄不足 → 毛利率降至21.9% → 三项失效条件同时触发"
            ),
            fact_excerpt=(
                "2023年营业收入同比-8.6%、毛利率21.9%、平均产能利用率75.0%，"
                "分别低于0%、25%、80%的历史逻辑阈值。"
            ),
            source_document_id=DOCUMENT_ID,
            source_document_title=document.title,
            disclosed_at=DISCLOSED_AT,
            occurred_at=date(2023, 12, 31),
            source_url=SOURCE_URL,
            ai_status="候选",
            ai_confidence=Decimal("0.97"),
            model_version=settings.llm_model_version,
            prompt_version=settings.prompt_version,
            confirmation_status="待确认",
            review_status="待复核",
        )
        session.add(evidence)
        relation = EvidenceRelation(
            relation_id=RELATION_ID,
            evidence_id=EVIDENCE_ID,
            thesis_id=DEMO_THESIS_ID,
            hypothesis_id=HYPOTHESIS_IDS["demand"],
            direction="冲突",
            strength="高",
            reason="年报披露营业收入同比转负，直接冲突于需求复苏假设",
            status="待确认",
            created_by="preset_ai",
        )
        session.add(relation)
        mappings = {
            row.hypothesis_id: row
            for row in session.scalars(
                select(HypothesisMetricMap).where(
                    HypothesisMetricMap.hypothesis_id.in_(HYPOTHESIS_IDS.values())
                )
            ).all()
        }
        for key, hypothesis_id in HYPOTHESIS_IDS.items():
            mapping = mappings.get(hypothesis_id)
            if mapping is None:
                raise ValidationFailed(f"演示逻辑缺少指标映射：{hypothesis_id}")
            session.add(
                MetricObservation(
                    security_id=thesis.security_id,
                    metric_id=mapping.metric_id,
                    metric_version=mapping.metric_version,
                    period="FY2023",
                    period_type="年度",
                    observation_date=DISCLOSED_AT.date(),
                    actual_value=OBSERVATIONS[key],
                    raw_value=f"{OBSERVATIONS[key]}%",
                    unit="%",
                    source_document_id=DOCUMENT_ID,
                    data_version=digest,
                    is_illustrative=False,
                )
            )
        _timeline(
            session,
            thesis_id=thesis.thesis_id,
            actor=actor.user_id,
            action="上传公开年报",
            dimension="material",
            event_type="annual_report_uploaded",
            actor_type="human",
            summary=f"上传并解析《{document.title}》（{filename}）",
            related_object_type="document",
            related_object_id=document.document_id,
            after={"document_id": document.document_id, "content_hash": digest},
        )
        _timeline(
            session,
            thesis_id=thesis.thesis_id,
            actor="preset_ai",
            action="生成重大风险候选",
            dimension="ai_analysis",
            event_type="risk_analysis_created",
            actor_type="preset_ai",
            summary="识别三项年度指标同时突破历史逻辑失效阈值",
            related_object_type="evidence",
            related_object_id=evidence.evidence_id,
            after={
                "revenue_yoy": "-8.6%",
                "gross_margin": "21.9%",
                "capacity_utilization": "75.0%",
                "direction": "冲突",
                "strength": "高",
                "confidence": "0.97",
            },
            detail_url=(
                f"/evidence/{evidence.evidence_id}/analysis?"
                f"thesisId={DEMO_THESIS_ID}&relationId={relation.relation_id}"
            ),
        )
        session.flush()

        uow = build_uow(session)
        thesis_record = uow.thesis.get(DEMO_THESIS_ID)
        if thesis_record is None:
            raise ValidationFailed("演示投资逻辑不存在")
        hypotheses = uow.thesis.list_hypotheses(DEMO_THESIS_ID)
        suggestion = status.compute_suggestion(
            uow,
            thesis=thesis_record,
            hypotheses=hypotheses,
            thresholds=settings.rules,
            today=DISCLOSED_AT.date(),
        )
        if suggestion.suggested_status.value != "重大风险":
            raise ValidationFailed(
                f"演示规则配置错误：预期重大风险，实际为{suggestion.suggested_status.value}；"
                f"{'；'.join(suggestion.reasons)}"
            )
        _timeline(
            session,
            thesis_id=DEMO_THESIS_ID,
            actor="system",
            action="更新假设健康投影",
            dimension="hypothesis_health",
            event_type="invalidation_metrics_triggered",
            actor_type="system",
            summary="FY2023 三项指标均触发失效条件，健康投影更新为承压",
            related_object_type="document",
            related_object_id=DOCUMENT_ID,
            after={METRIC_NAMES[key]: f"{OBSERVATIONS[key]}%" for key in HYPOTHESIS_IDS},
            reason="三项条件要求连续1期，本次FY2023观察均低于阈值",
        )
        session.flush()
    return _upload_result(material=material, duplicate=False)


def _upload_result(*, material: dict[str, str], duplicate: bool) -> dict[str, Any]:
    return {
        "document_id": material["document_id"],
        "evidence_ids": [material["evidence_id"]],
        "relation_ids": [material["relation_id"]],
        "result_source": "preset_ai_result",
        "duplicate": duplicate,
        "next_url": (
            f"/evidence/{material['evidence_id']}/analysis?"
            f"thesisId={DEMO_THESIS_ID}&relationId={material['relation_id']}"
        ),
    }


def get_analysis(*, evidence_id: str, relation_id: str, actor: Actor) -> dict[str, Any]:
    from app.db.models.core import Document, Evidence, EvidenceRelation, Hypothesis

    with _session_scope() as session:
        evidence = session.get(Evidence, evidence_id)
        relation = session.get(EvidenceRelation, relation_id)
        if (
            evidence is None
            or relation is None
            or relation.evidence_id != evidence.evidence_id
            or relation.status == "已解除"
        ):
            raise NotVisible("证据不存在或无访问权限")
        thesis = _visible_thesis(session, relation.thesis_id, actor)
        hypothesis = session.get(Hypothesis, relation.hypothesis_id)
        document = session.get(Document, evidence.source_document_id)
        if hypothesis is None or document is None:
            raise ValidationFailed("演示分析结果配置异常")
        affected_hypotheses = []
        for key, affected_id in HYPOTHESIS_IDS.items():
            affected = session.get(Hypothesis, affected_id)
            if affected is None:
                raise ValidationFailed(f"演示分析缺少受影响假设：{affected_id}")
            affected_hypotheses.append(
                {
                    "hypothesis_id": affected.hypothesis_id,
                    "statement": affected.statement,
                    "metric_name": METRIC_NAMES[key],
                    "actual_value": f"{OBSERVATIONS[key]}%",
                    "invalidation_threshold": f"{THRESHOLDS[key]}%",
                    "direction": "冲突",
                }
            )
        return {
            "evidence_id": evidence.evidence_id,
            "relation_id": relation.relation_id,
            "document_id": document.document_id,
            "document_title": document.title or "",
            "disclosed_at": evidence.disclosed_at,
            "fact_excerpt": evidence.fact_excerpt or "",
            "hypothesis_id": hypothesis.hypothesis_id,
            "hypothesis_statement": hypothesis.statement,
            "affected_hypotheses": affected_hypotheses,
            "direction": relation.direction,
            "strength": relation.strength or evidence.strength or "中",
            "transmission_path": evidence.transmission_path or "",
            "ai_confidence": str(evidence.ai_confidence or ""),
            "ai_status": evidence.ai_status or "候选",
            "model_version": evidence.model_version or "",
            "prompt_version": evidence.prompt_version or "",
            "evidence_locator": evidence.evidence_locator,
            "result_source": "preset_ai_result",
            "relation_status": relation.status,
            "can_manage": thesis.owner == actor.user_id,
            "review_reason": relation.reason,
        }


def get_citation(*, document_id: str, locator: str, actor: Actor) -> dict[str, Any]:
    from sqlalchemy import select

    from app.db.models.core import Document, DocumentSegment, Evidence

    with _session_scope() as session:
        document = session.get(Document, document_id)
        target = session.scalar(
            select(DocumentSegment).where(
                DocumentSegment.document_id == document_id,
                DocumentSegment.locator == locator,
            )
        )
        evidence = session.scalar(
            select(Evidence).where(
                Evidence.source_document_id == document_id,
                Evidence.evidence_locator == locator,
            )
        )
        if document is None or target is None or evidence is None:
            raise NotVisible("引用不存在或无访问权限")
        _visible_thesis(session, evidence.thesis_id, actor)
        previous = session.scalar(
            select(DocumentSegment).where(
                DocumentSegment.document_id == document_id,
                DocumentSegment.ordinal == target.ordinal - 1,
            )
        )
        next_segment = session.scalar(
            select(DocumentSegment).where(
                DocumentSegment.document_id == document_id,
                DocumentSegment.ordinal == target.ordinal + 1,
            )
        )

        def segment_out(segment: Any | None) -> dict[str, Any] | None:
            if segment is None:
                return None
            return {
                "locator": segment.locator,
                "ordinal": segment.ordinal,
                "page": segment.page,
                "content": segment.content,
            }

        return {
            "document_id": document.document_id,
            "document_title": document.title or "",
            "document_type": document.doc_type or "",
            "disclosed_at": document.published_at,
            "locator": target.locator,
            "page": target.page,
            "previous": segment_out(previous),
            "target": segment_out(target),
            "next": segment_out(next_segment),
            "source_url": evidence.source_url,
        }


def get_hypothesis_health(*, thesis_id: str, actor: Actor) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db.models.core import (
        EvidenceRelation,
        Hypothesis,
        HypothesisMetricMap,
        Metric,
        MetricObservation,
    )

    with _session_scope() as session:
        thesis = _visible_thesis(session, thesis_id, actor)
        hypotheses = session.scalars(
            select(Hypothesis)
            .where(Hypothesis.thesis_id == thesis_id)
            .order_by(Hypothesis.hypothesis_id)
        ).all()
        relations = session.scalars(
            select(EvidenceRelation).where(
                EvidenceRelation.thesis_id == thesis_id,
                EvidenceRelation.status != "已解除",
            )
        ).all()
        mappings = {
            row.hypothesis_id: row
            for row in session.scalars(
                select(HypothesisMetricMap).where(
                    HypothesisMetricMap.hypothesis_id.in_(
                        [hypothesis.hypothesis_id for hypothesis in hypotheses]
                    )
                )
            ).all()
        }
        uploaded_observations = {
            row.metric_id: row
            for row in session.scalars(
                select(MetricObservation).where(
                    MetricObservation.security_id == thesis.security_id,
                    MetricObservation.source_document_id == DOCUMENT_ID,
                    MetricObservation.data_version == MATERIAL_HASH,
                )
            ).all()
        }
        result = []
        for hypothesis in hypotheses:
            related = [item for item in relations if item.hypothesis_id == hypothesis.hypothesis_id]
            support = sum(item.status == "已确认" and item.direction == "支持" for item in related)
            conflict = sum(item.status == "已确认" and item.direction == "冲突" for item in related)
            pending = sum(item.status == "待确认" for item in related)
            mapping = mappings.get(hypothesis.hypothesis_id)
            observation = (
                uploaded_observations.get(mapping.metric_id) if mapping is not None else None
            )
            metric_row = (
                session.get(Metric, (mapping.metric_id, mapping.metric_version))
                if mapping is not None
                else None
            )
            breached = bool(
                observation is not None
                and observation.actual_value is not None
                and mapping is not None
                and mapping.invalidation_threshold is not None
                and observation.actual_value < mapping.invalidation_threshold
            )
            if breached and mapping is not None and observation is not None:
                health, reason = (
                    "承压",
                    f"FY2023 {metric_row.name if metric_row else mapping.metric_id}"
                    f"{observation.actual_value}%低于失效阈值"
                    f"{mapping.invalidation_threshold}%，已满足连续1期失效条件",
                )
            elif support and conflict:
                health, reason = "有分歧", "已确认支持与冲突证据同时存在"
            elif conflict:
                health, reason = "承压", "存在已确认冲突证据"
            elif support:
                health, reason = "增强", "存在已确认支持证据"
            elif pending:
                health, reason = "待验证", "存在尚待负责人确认的候选关系"
            else:
                health, reason = "稳定", "当前没有新增关系改变证据结构"
            metric = {
                "name": metric_row.name if metric_row else "未配置指标",
                "value": (
                    f"{observation.actual_value}%"
                    if observation is not None and observation.actual_value is not None
                    else "待披露"
                ),
                "trend": "FY2023触发失效" if breached else "等待年报观测",
            }
            result.append(
                {
                    "hypothesis_id": hypothesis.hypothesis_id,
                    "statement": hypothesis.statement,
                    "importance": hypothesis.importance,
                    "support_confirmed": support,
                    "conflict_confirmed": conflict,
                    "pending": pending,
                    "health": health,
                    "health_reason": reason,
                    "metric": metric,
                    "invalidation": hypothesis.invalidation_rule or "未设置",
                }
            )
        return result


def get_timeline(
    *,
    thesis_id: str,
    actor: Actor,
    dimension: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    from sqlalchemy import func, select

    from app.db.models.governance import AuditLog

    with _session_scope() as session:
        _visible_thesis(session, thesis_id, actor)
        conditions = [
            AuditLog.object_type == "thesis_timeline",
            AuditLog.object_id == thesis_id,
        ]
        if dimension:
            conditions.append(AuditLog.detail["dimension"].astext == dimension)
        total = int(
            session.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
        )
        rows = session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.occurred_at, AuditLog.id)
            .limit(limit)
            .offset(offset)
        ).all()
        items = []
        for row in rows:
            detail = row.detail or {}
            items.append(
                {
                    "event_id": f"TL-{row.id}",
                    "thesis_id": thesis_id,
                    "dimension": detail["dimension"],
                    "event_type": detail["event_type"],
                    "occurred_at": row.occurred_at,
                    "actor_type": detail["actor_type"],
                    "actor_name": row.actor,
                    "summary": detail["summary"],
                    "related_object_type": detail.get("related_object_type"),
                    "related_object_id": detail.get("related_object_id"),
                    "before": detail.get("before"),
                    "after": detail.get("after"),
                    "reason": detail.get("reason"),
                    "detail_url": detail.get("detail_url"),
                }
            )
        return {"items": items, "total": total, "limit": limit, "offset": offset}
