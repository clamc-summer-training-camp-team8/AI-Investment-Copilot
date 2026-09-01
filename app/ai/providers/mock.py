"""测试和演示用 Provider。

MockProvider 不调用网络。默认复用 LocalProvider，调用方也可以注入固定 payload
来测试 Schema 校验、低置信度和异常路径。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.ai.providers.local import LocalProvider
from app.core.config import Settings


class MockProvider(LocalProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        event_payload: dict[str, Any] | None = None,
        thesis_payload: dict[str, Any] | None = None,
        answer_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(settings)
        self._event_payload = event_payload
        self._thesis_payload = thesis_payload
        self._answer_payload = answer_payload

    def analyze_event_impact(self, **kwargs: Any) -> dict[str, Any]:
        if self._event_payload is not None:
            return deepcopy(self._event_payload)
        return super().analyze_event_impact(**kwargs)

    def draft_thesis(self, **kwargs: Any) -> dict[str, Any]:
        if self._thesis_payload is not None:
            return deepcopy(self._thesis_payload)
        return super().draft_thesis(**kwargs)

    def answer_knowledge(self, **kwargs: Any) -> dict[str, Any]:
        if self._answer_payload is not None:
            return deepcopy(self._answer_payload)
        return super().answer_knowledge(**kwargs)
