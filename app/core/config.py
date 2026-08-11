"""运行配置。

规则阈值单独放在 RuleThresholds：PRD 5.2 的"重要支持与冲突同时存在""接近失效条件"
在文档里是散文描述，必须参数化才能被规则引擎实现和回归测试。
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RuleThresholds(BaseSettings):
    """状态建议与失效判定阈值。变更需记版本，历史结论不得被新阈值覆盖。"""

    model_config = SettingsConfigDict(env_prefix="RULE_", extra="ignore")

    version: str = "rules-v1"

    # 出现分歧：同一核心假设上已确认的支持与冲突证据均达到该条数
    divergence_min_support: int = 1
    divergence_min_conflict: int = 1

    # 重大风险：距失效阈值的相对差距进入该比例内视为"接近"
    near_invalidation_ratio: float = 0.1

    # 失效条件默认连续观察期数
    consecutive_breach_periods: int = 2

    # 低于该置信度的 AI 输出降级进人工队列，且不触发重大风险提醒
    low_confidence_cutoff: float = 0.6

    # 趋势展示的观察期数范围（FR-V-002：最近 4 至 8 期）
    trend_min_periods: int = 4
    trend_max_periods: int = 8


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Investment Copilot"
    env: str = "local"
    debug: bool = True

    database_url: str = "postgresql+psycopg://copilot:copilot@localhost:5432/copilot"

    storage_dir: Path = PROJECT_ROOT / "storage"
    # 样例包全部为虚构演示数据，导入时一律标记 is_illustrative
    sample_pack_dir: Path = PROJECT_ROOT / "docs" / "data" / "数据分析交付包" / "业务样例包"

    # 模型网关。local 使用规则实现，不外发任何数据。
    llm_provider: str = Field(default="local", pattern="^(local|http|mock)$")
    llm_endpoint: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2
    llm_model_version: str = "local-rule-v1"
    prompt_version: str = "prompts-v1"

    llm_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    llm_thinking_mode: str = Field(default='disabled', pattern='^(enabled|disabled)$')
    llm_reasoning_effort: str = Field(default='low', pattern='^(low|high|max)$')
    llm_input_cost_per_million: Decimal = Field(default=Decimal('0'), ge=0)
    llm_output_cost_per_million: Decimal = Field(default=Decimal('0'), ge=0)

    # RAG 向量由固定维度的数据库列承载。更换模型前必须先迁移列维度。
    embedding_provider: str = Field(default='local', pattern='^(local|http)$')
    embedding_endpoint: str | None = None
    embedding_api_key: str | None = None
    embedding_model_version: str = 'local-hash-v1'
    embedding_dimensions: int = Field(default=384, ge=32, le=4096)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    redis_url: str = 'redis://localhost:6379/0'
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    runtime_max_attempts: int = Field(default=3, ge=1, le=10)

    # 本地开发允许可信请求头；非本地环境必须使用 JWT。
    auth_mode: str = Field(default='trusted_headers', pattern='^(trusted_headers|jwt)$')
    auth_jwt_secret: str | None = None
    auth_jwt_algorithm: str = Field(default='HS256', pattern='^HS(256|384|512)$')
    auth_jwt_issuer: str = 'ai-investment-copilot'
    auth_jwt_audience: str = 'ai-investment-copilot-api'
    auth_jwt_leeway_seconds: int = Field(default=30, ge=0, le=300)
    cors_origins: list[str] = ['http://localhost:5173']
    rate_limit_enabled: bool = False
    rate_limit_requests_per_minute: int = Field(default=60, ge=1, le=10000)
    idempotency_ttl_seconds: int = Field(default=86400, ge=60, le=604800)

    rules: RuleThresholds = Field(default_factory=RuleThresholds)


settings = Settings()
