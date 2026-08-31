from __future__ import annotations

from datetime import UTC, datetime

from app.ai.gateway import Gateway
from app.core.config import Settings
from app.core.enums import AiStatus


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_mock_provider_复用本地规则并通过事件契约() -> None:
    gateway = Gateway.build(_settings(llm_provider="mock"))

    outcome = gateway.event_impact(
        document_id="doc-001",
        security_id="000538.SZ",
        segment_locator="doc-001#paragraph-1",
        segment_text="公司收入增长，订单持续提升。",
        disclosure_time=datetime.now(UTC).isoformat(),
        candidates=[
            {
                "thesis_id": "THS-001",
                "hypothesis_id": "H1",
                "statement": "收入保持增长",
            }
        ],
        evidence_contexts=[],
    )

    assert outcome.ai_status is AiStatus.CANDIDATE
    assert outcome.payload["event"]["evidence_locator"] == "doc-001#paragraph-1"
    assert outcome.payload["impacts"][0]["hypothesis_id"] == "H1"


def test_http_provider_缺少端点时明确失败() -> None:
    try:
        Gateway.build(_settings(llm_provider="http"))
    except Exception as exc:
        assert "LLM_ENDPOINT" in str(exc)
    else:
        raise AssertionError("缺少 LLM_ENDPOINT 时不应构造成功")
