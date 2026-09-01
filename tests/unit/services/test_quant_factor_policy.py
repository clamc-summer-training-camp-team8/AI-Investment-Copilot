from datetime import datetime
from decimal import Decimal

import pytest

from app.calc.portfolio import PortfolioConfig
from app.core.timeutil import BUSINESS_TZ
from app.services.quant import (
    QuantSignalInput,
    governed_signal_score,
    quant_factor_catalog,
    quant_model_templates,
    resolve_quant_model_template,
)


def test_组合研究分数不使用_ai_置信度() -> None:
    generated = datetime(2026, 8, 12, 18, tzinfo=BUSINESS_TZ)
    low_confidence = QuantSignalInput(
        signal_id="SIG-LOW",
        disclosed_at=generated,
        generated_at=generated,
        direction="支持",
        strength="中",
        confidence=Decimal("0.10"),
    )
    high_confidence = QuantSignalInput(
        signal_id="SIG-HIGH",
        disclosed_at=generated,
        generated_at=generated,
        direction="支持",
        strength="中",
        confidence=Decimal("0.99"),
    )

    assert governed_signal_score(low_confidence) == Decimal("0.7")
    assert governed_signal_score(high_confidence) == Decimal("0.7")


def test_因子目录明确区分当前生效_数据门禁和规划项() -> None:
    factors = {item.factor_id: item for item in quant_factor_catalog()}

    assert factors["confirmed_event_direction_strength"].status == "active"
    assert factors["industry_neutralization"].status == "gated"
    assert factors["average_net_exposure"].status == "active"
    assert factors["momentum_20_60_120"].status == "planned"
    assert {item.version for item in factors.values()} == {"1.0.0"}
    assert (
        "AI 判断置信度不参与 Alpha 权重"
        in factors["confirmed_event_direction_strength"].limitations
    )


def test_模型模板只允许已发布版本进入运行() -> None:
    templates = {item.template_id: item for item in quant_model_templates()}

    active = resolve_quant_model_template("confirmed-event-research-v3", PortfolioConfig())
    assert active.version == "3.0.0"
    assert templates["confirmed-event-industry-neutral-v3"].status == "gated"
    with pytest.raises(ValueError, match="尚未发布"):
        resolve_quant_model_template("event-momentum-overlay-v1", PortfolioConfig())


def test_行业中性模板强制保留行业中性参数() -> None:
    with pytest.raises(ValueError, match="neutralize_industry=true"):
        resolve_quant_model_template(
            "confirmed-event-industry-neutral-v3", PortfolioConfig(neutralize_industry=False)
        )

    template = resolve_quant_model_template(
        "confirmed-event-industry-neutral-v3", PortfolioConfig(neutralize_industry=True)
    )
    assert template.required_config == {"neutralize_industry": True}
