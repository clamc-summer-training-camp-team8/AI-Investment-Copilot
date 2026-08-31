"""Runtime 状态观察接口与模型用量归一化。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from app.core.config import Settings

if TYPE_CHECKING:
    from app.ai.runtime import RuntimeExecution


@dataclass(frozen=True)
class ModelCallUsage:
    provider: str
    model_version: str
    prompt_version: str | None = None
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int | None = None
    attempt_count: int = 1
    cost_amount: Decimal | None = None
    currency: str = "CNY"
    success: bool = True
    error_code: str | None = None


class RuntimeRecorder(Protocol):
    """持久化由外层注入，Runtime 不依赖 SQLAlchemy。"""

    def started(self, execution: RuntimeExecution) -> None: ...

    def checkpoint(self, execution: RuntimeExecution) -> None: ...

    def finished(self, execution: RuntimeExecution) -> None: ...


class NullRuntimeRecorder:
    def started(self, execution: RuntimeExecution) -> None:
        return None

    def checkpoint(self, execution: RuntimeExecution) -> None:
        return None

    def finished(self, execution: RuntimeExecution) -> None:
        return None


def usage_from_payload(payload: dict[str, Any], settings: Settings) -> ModelCallUsage:
    """兼容 OpenAI 与 DeepSeek usage 字段，并按配置估算成本。"""
    metadata = payload.get("model_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    usage = metadata.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = _integer(usage.get("prompt_tokens", usage.get("input_tokens")))
    output_tokens = _integer(usage.get("completion_tokens", usage.get("output_tokens")))
    total_tokens = _integer(usage.get("total_tokens")) or input_tokens + output_tokens
    cost = None
    if (
        settings.llm_input_cost_per_million is not None
        and settings.llm_output_cost_per_million is not None
    ):
        cost = (
            Decimal(input_tokens) * Decimal(str(settings.llm_input_cost_per_million))
            + Decimal(output_tokens) * Decimal(str(settings.llm_output_cost_per_million))
        ) / Decimal(1_000_000)
    provider = str(metadata.get("provider") or settings.llm_provider)
    return ModelCallUsage(
        provider=provider,
        model_version=str(payload.get("model_version") or settings.llm_model_version),
        prompt_version=_optional_string(payload.get("prompt_version")),
        request_id=_optional_string(metadata.get("request_id")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        latency_ms=_optional_integer(metadata.get("latency_ms")),
        attempt_count=max(_integer(metadata.get("attempt_count")), 1),
        cost_amount=cost.quantize(Decimal("0.00000001")) if cost is not None else None,
    )


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def _optional_integer(value: object) -> int | None:
    result = _integer(value)
    return result if result > 0 else None


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
