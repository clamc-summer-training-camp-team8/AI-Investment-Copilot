"""配置中的路径必须与仓库实际布局一致。

归档需求文档时移动过样例包目录，config 里的路径没跟着改会让 seed 脚本
静默读到空目录。这个测试防止再次发生。
"""

from __future__ import annotations

from app.core.config import PROJECT_ROOT, settings


def test_项目根指向仓库根() -> None:
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / ".importlinter").is_file()


def test_样例包路径存在且含样例数据() -> None:
    assert settings.sample_pack_dir.is_dir()
    assert (settings.sample_pack_dir / "样例指标历史数据.csv").is_file()
    assert (settings.sample_pack_dir / "样例预期AI输出.json").is_file()


def test_默认模型提供者不外发数据() -> None:
    """local 使用规则实现，其他模块开发与 CI 都不依赖外部服务（PRD 12.1）。"""
    assert settings.llm_provider == "local"
    assert not settings.llm_endpoint


def test_规则阈值带版本号() -> None:
    """阈值变更需记版本，历史结论不得被新阈值覆盖。"""
    assert settings.rules.version
