"""仓库结构与文档一致性守门测试。

模块 README 与代码不一致视为缺陷（docs/collaboration/README.md 第 7 节）。
这个文件把这条约定变成可执行检查：新增模块忘了写 README、或者忘了在
根 README 的模块表里登记，CI 会直接失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODULES_REQUIRING_README = [
    "app/core",
    "app/db",
    "app/calc",
    "app/ingest",
    "app/ai",
    "app/services",
    "app/api",
    "app/schemas",
    "app/workers",
    "analytics",
    "web",
    "contracts",
    "alembic",
    "tests",
    "deploy",
    "scripts",
]

REQUIRED_TOP_LEVEL = [
    "README.md",
    "CONTRIBUTING.md",
    "Makefile",
    "pyproject.toml",
    ".importlinter",
    ".env.example",
    ".gitignore",
    ".github/CODEOWNERS",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    "docs/architecture/README.md",
    "docs/architecture/layering.md",
    "docs/collaboration/README.md",
    "docs/adr/README.md",
    # 被 Makefile 与 deploy/README.md 直接引用，缺失会让 make seed / 起环境静默失败
    "scripts/seed_sample_pack.py",
    "deploy/docker-compose.local.yml",
]


@pytest.mark.parametrize("module", MODULES_REQUIRING_README)
def test_每个模块都有_readme(module: str) -> None:
    readme = PROJECT_ROOT / module / "README.md"
    assert readme.is_file(), f"{module} 缺少 README.md"
    assert readme.read_text(encoding="utf-8").strip(), f"{module}/README.md 为空"


@pytest.mark.parametrize("path", REQUIRED_TOP_LEVEL)
def test_协作与工程约束文件齐备(path: str) -> None:
    assert (PROJECT_ROOT / path).is_file(), f"缺少 {path}"


@pytest.mark.parametrize("module", MODULES_REQUIRING_README)
def test_根_readme_登记了每个模块(module: str) -> None:
    root_readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert module in root_readme, f"根 README 的模块表未登记 {module}"


def test_需求基线文档已归档() -> None:
    """基线文档只由产品负责人更新，位置固定，其他文档引用它们的路径。"""
    assert (PROJECT_ROOT / "docs/product").is_dir()
    assert (PROJECT_ROOT / "docs/data/数据分析交付包").is_dir()
    assert list((PROJECT_ROOT / "docs/product").glob("*.docx"))


def test_样例包位置未变() -> None:
    """app/core/config.py 的 sample_pack_dir 与 scripts/seed 都依赖这个路径。"""
    sample_pack = PROJECT_ROOT / "docs/data/数据分析交付包/业务样例包"
    assert sample_pack.is_dir()
    assert (sample_pack / "样例指标历史数据.csv").is_file()


def test_codeowners_覆盖每个模块() -> None:
    codeowners = (PROJECT_ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    for module in MODULES_REQUIRING_README:
        assert f"/{module}/" in codeowners, f"CODEOWNERS 未配置 {module} 的负责人"


def test_分层契约覆盖每个后端模块() -> None:
    """新增 app 子模块忘了写进 .importlinter，等于该模块处于无约束状态。"""
    config = (PROJECT_ROOT / ".importlinter").read_text(encoding="utf-8")
    for path in sorted((PROJECT_ROOT / "app").iterdir()):
        if not path.is_dir() or path.name.startswith((".", "__")):
            continue
        assert f"app.{path.name}" in config, f".importlinter 未约束 app.{path.name}"


def test_make_check_与_ci_门禁一致() -> None:
    """本地 make check 与 CI 跑的检查项必须一致，否则本地通过远端仍会红。"""
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    ci = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for gate in ["ruff check", "ruff format", "mypy", "lint-imports", "check_contracts"]:
        assert gate in makefile, f"Makefile 缺少门禁 {gate}"
        assert gate in ci, f"CI 缺少门禁 {gate}"
