"""运行配置。

规则阈值单独放在 RuleThresholds：PRD 5.2 的"重要支持与冲突同时存在""接近失效条件"
在文档里是散文描述，必须参数化才能被规则引擎实现和回归测试。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
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
    llm_api_key: SecretStr | None = None
    llm_model_version: str = "local-rule-v1"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    llm_thinking_mode: str = Field(default="disabled", pattern="^(enabled|disabled)$")
    llm_reasoning_effort: str = Field(default="low", pattern="^(low|high|max)$")
    llm_input_cost_per_million: float | None = Field(default=None, ge=0)
    llm_output_cost_per_million: float | None = Field(default=None, ge=0)
    # 排序检查员与生成链路分开开关；默认禁用，避免误将投研材料外发。
    ranking_judge_enabled: bool = False
    ranking_judge_endpoint: str = "https://api.openai.com/v1/responses"
    ranking_judge_model_version: str = "gpt-5.6-terra"
    ranking_judge_candidate_limit: int = Field(default=40, ge=5, le=100)
    ranking_judge_weight: float = Field(default=0.3, ge=0, le=0.5)
    runtime_max_attempts: int = Field(default=3, ge=1, le=10)
    prompt_version: str = "prompts-v1"

    # Docker Desktop publishes Redis on the host IPv4 loopback.  Using
    # ``localhost`` is unreliable on machines where it resolves to ``::1``
    # first while the published port only listens on IPv4.
    redis_url: str = "redis://127.0.0.1:6379/0"
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    upload_retention_days: int = Field(default=30, ge=1, le=3650)
    failed_upload_retention_days: int = Field(default=90, ge=1, le=3650)

    # 原文件事实源。上传原件先按内容哈希写入 S3-compatible 存储，再进入处理队列。
    object_store_endpoint: str = "http://127.0.0.1:9000"
    object_store_access_key: str = "copilot"
    object_store_secret_key: SecretStr = SecretStr("copilot-local-only")
    object_store_bucket: str = "copilot-documents"
    object_store_region: str = "us-east-1"
    object_store_secure: bool = False
    object_store_retention_days: int = Field(default=365, ge=1, le=3650)
    chunker_version: str = "semantic-v1"
    extractor_version: str = "event-v1"
    # P1 默认模型为完全离线、可复现的字符哈希 embedding。它只用于建立检索
    # 基线；换成正式模型时必须改版本号，旧向量不覆盖。
    embedding_version: str | None = "hash-char-2gram-v1"
    rag_hybrid_keyword_weight: float = Field(default=0.45, ge=0, le=1)
    rag_hybrid_vector_weight: float = Field(default=0.55, ge=0, le=1)
    # 事件→假设 RAG 试点默认关闭。开启后仍按事件稳定采样，召回内容只进入
    # 模型候选上下文，不参与鉴权、确定性规则或最终状态变更。
    rag_event_pilot_enabled: bool = False
    rag_event_pilot_sample_rate: float = Field(default=0.05, ge=0, le=1)
    rag_event_pilot_limit: int = Field(default=3, ge=1, le=10)

    # 本地开发可由受信任网关注入请求头；试点/生产必须使用带签名和过期时间的 JWT。
    auth_mode: str = Field(default="trusted_headers", pattern="^(trusted_headers|jwt)$")
    auth_jwt_secret: SecretStr | None = None
    auth_jwt_algorithm: str = Field(default="HS256", pattern="^HS(256|384|512)$")
    auth_jwt_issuer: str = "ai-investment-copilot"
    auth_jwt_audience: str = "ai-investment-copilot-api"
    auth_jwt_leeway_seconds: int = Field(default=30, ge=0, le=300)
    cors_origins: list[str] = ["http://localhost:5173"]

    rules: RuleThresholds = Field(default_factory=RuleThresholds)


settings = Settings()
