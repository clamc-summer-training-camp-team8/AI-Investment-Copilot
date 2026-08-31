"""离线市场数据调用的有限重试与脱敏审计。"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TypeVar

from app.ingest.market_source_secrets import sanitize_secret_text
from app.ingest.market_sources import MarketSourceError

T = TypeVar("T")


@dataclass(frozen=True)
class MarketRetryEvent:
    operation: str
    attempt: int
    max_attempts: int
    error_type: str
    reason: str
    wait_seconds: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def call_market_source(
    operation: str,
    call: Callable[[], T],
    *,
    max_attempts: int = 3,
    wait_seconds: float = 1.0,
    secrets: tuple[str, ...] = (),
    events: list[MarketRetryEvent] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> T:
    """执行有限重试；最终异常与审计事件均不包含凭证。"""

    if max_attempts < 1:
        raise ValueError("max_attempts 必须至少为 1")
    if wait_seconds < 0:
        raise ValueError("wait_seconds 不能为负")
    for attempt in range(1, max_attempts + 1):
        try:
            return call()
        except Exception as exc:
            reason = sanitize_secret_text(f"{type(exc).__name__}: {exc}", secrets=secrets)
            is_final = attempt == max_attempts
            event = MarketRetryEvent(
                operation=operation,
                attempt=attempt,
                max_attempts=max_attempts,
                error_type=type(exc).__name__,
                reason=reason,
                wait_seconds=0 if is_final else wait_seconds,
            )
            if events is not None:
                events.append(event)
            if is_final:
                raise MarketSourceError(
                    f"{operation} 在 {max_attempts} 次尝试后失败: {reason}"
                ) from exc
            sleeper(wait_seconds)
    raise AssertionError("重试循环不应到达此处")
