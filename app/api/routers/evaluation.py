"""离线评测与发布门禁的只读 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.api.deps import ActorDep, SettingsDep
from app.schemas.evaluation import GoldQualityReportOut
from app.services.evaluation_quality import QualityReportUnavailable, load_gold_quality_report

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/gold-quality", response_model=GoldQualityReportOut)
def get_gold_quality(actor: ActorDep, conf: SettingsDep) -> GoldQualityReportOut:
    del actor
    try:
        payload = load_gold_quality_report(conf.gold_quality_report_path)
        return GoldQualityReportOut.model_validate(payload)
    except (QualityReportUnavailable, ValidationError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
