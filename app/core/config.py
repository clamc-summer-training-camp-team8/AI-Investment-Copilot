"""运行配置。

规则阈值单独放在 RuleThresholds：PRD 5.2 的"重要支持与冲突同时存在""接近失效条件"
在文档里是散文描述，必须参数化才能被规则引擎实现和回归测试。
"""

from __future__ import annotations

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
    llm_provider: str = Field(default="local", pattern="^(local|http)$")
    llm_endpoint: str | None = None
    llm_model_version: str = "local-rule-v1"
    prompt_version: str = "prompts-v1"

    rules: RuleThresholds = Field(default_factory=RuleThresholds)


settings = Settings()
