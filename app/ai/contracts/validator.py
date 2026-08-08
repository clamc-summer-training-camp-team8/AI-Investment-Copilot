"""AI 输出的契约校验与降级。

两条降级规则（PRD 10.5 / FR-R-007），都必须可测试：

1. Schema 校验失败 → `ai_status = 解析失败`，进人工队列，**不抛给用户**。
   PRD 10.1 允许「JSON 修复一次」，因此这里先尝试一次修复再判失败。
2. `confidence < low_confidence_cutoff`（默认 0.6）→ `ai_status = 低置信`，
   进人工队列，**不触发重大风险提醒**。

校验通过不等于可以入正式证据链。所有输出的 `requires_human_review` 恒为真，
人工闸门在 app/services。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from app.core.config import PROJECT_ROOT, RuleThresholds
from app.core.enums import AiStatus

CONTRACTS_DIR = PROJECT_ROOT / "contracts" / "ai"


@dataclass
class ValidationOutcome:
    """校验结果。payload 始终返回，便于失败时也能保留原始输出给人工看。"""

    ai_status: AiStatus
    payload: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    repaired: bool = False

    @property
    def usable(self) -> bool:
        """能否进入业务流程。解析失败的输出只能进人工队列。"""
        return self.ai_status is not AiStatus.PARSE_FAILED

    @property
    def triggers_major_risk_alert(self) -> bool:
        """FR-R-007：低置信不升级提醒。"""
        return self.ai_status is AiStatus.CANDIDATE


@lru_cache(maxsize=8)
def load_schema(name: str) -> dict[str, Any]:
    path = CONTRACTS_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"契约文件不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _repair(payload: dict[str, Any]) -> dict[str, Any]:
    """一次性修复常见结构偏差（PRD 10.1「JSON 修复一次」）。

    只做无歧义的搬运：样例包把版本字段嵌在 model_metadata 下，而契约要求顶层。
    不猜测缺失的业务值——补业务值等于伪造模型输出。
    """
    repaired = dict(payload)
    metadata = repaired.get("model_metadata")
    if isinstance(metadata, dict):
        for key in ("model_version", "prompt_version", "generated_at"):
            if key not in repaired and key in metadata:
                repaired[key] = metadata[key]
    return repaired


def validate(
    name: str,
    payload: dict[str, Any],
    *,
    thresholds: RuleThresholds,
    allow_repair: bool = True,
) -> ValidationOutcome:
    """校验并给出 ai_status。"""
    validator = Draft202012Validator(load_schema(name))
    errors = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(payload)]
    repaired = False

    if errors and allow_repair:
        candidate = _repair(payload)
        retry = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(candidate)]
        if not retry:
            payload, errors, repaired = candidate, [], True
        else:
            errors = retry

    if errors:
        return ValidationOutcome(
            ai_status=AiStatus.PARSE_FAILED,
            payload=payload,
            errors=errors,
            repaired=repaired,
        )

    confidence = _extract_confidence(payload)
    if confidence is not None and confidence < thresholds.low_confidence_cutoff:
        return ValidationOutcome(
            ai_status=AiStatus.LOW_CONFIDENCE,
            payload=payload,
            errors=[f"置信度 {confidence} 低于阈值 {thresholds.low_confidence_cutoff}"],
            repaired=repaired,
        )

    return ValidationOutcome(ai_status=AiStatus.CANDIDATE, payload=payload, repaired=repaired)


def _extract_confidence(payload: dict[str, Any]) -> float | None:
    signal = payload.get("signal")
    if isinstance(signal, dict) and isinstance(signal.get("confidence"), int | float):
        return float(signal["confidence"])
    if isinstance(payload.get("confidence"), int | float):
        return float(payload["confidence"])
    return None
