"""AI Skill 定义的加载与校验。

Skill 只描述单个模型任务的边界、输入和输出；检索、模型调用、持久化仍分别由
Agent、Gateway 和后端负责。这样既能让 prompt 随 Skill 版本演进，也不把通用
工作流引擎引入当前固定的四条业务链路。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_SKILLS_DIR = Path(__file__).with_name("skills")
_REQUIRED_METADATA = frozenset({"skill_key", "version", "schema"})
_SKILL_KEYS = frozenset(
    {
        "thesis-draft",
        "event-impact",
        "metric-explain",
        "metric-recommend",
        "review-draft",
        "hypothesis-quality",
    }
)


class SkillDefinitionError(ValueError):
    """Skill 文件缺失或格式不符合约定。"""


@dataclass(frozen=True)
class SkillDefinition:
    skill_key: str
    version: str
    schema_name: str
    path: Path
    system: str
    instruction: str


def load_skill(skill_key: str) -> SkillDefinition:
    """加载一个版本化 Skill，不接受运行时动态拼出的路径。"""
    if skill_key not in _SKILL_KEYS:
        raise SkillDefinitionError(f"未知 AI Skill: {skill_key}")
    path = _SKILLS_DIR / skill_key / "SKILL.md"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillDefinitionError(f"无法读取 AI Skill: {skill_key}") from exc

    metadata, body = _split_front_matter(raw, skill_key)
    if metadata["skill_key"] != skill_key:
        raise SkillDefinitionError(f"Skill 标识不匹配: {path}")
    system = _section(body, "System", "Instruction", skill_key)
    instruction = _section(body, "Instruction", None, skill_key)
    return SkillDefinition(
        skill_key=skill_key,
        version=metadata["version"],
        schema_name=metadata["schema"],
        path=path,
        system=system,
        instruction=instruction,
    )


def _split_front_matter(raw: str, skill_key: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---\n"):
        raise SkillDefinitionError(f"Skill 缺少 front matter: {skill_key}")
    try:
        header, body = raw[4:].split("\n---\n", maxsplit=1)
    except ValueError as exc:
        raise SkillDefinitionError(f"Skill front matter 未闭合: {skill_key}") from exc
    metadata = {
        key.strip(): value.strip()
        for line in header.splitlines()
        if ":" in line
        for key, value in [line.split(":", maxsplit=1)]
    }
    missing = _REQUIRED_METADATA - metadata.keys()
    if missing:
        raise SkillDefinitionError(f"Skill 缺少元数据 {sorted(missing)}: {skill_key}")
    return metadata, body


def _section(
    body: str,
    name: str,
    next_name: str | None,
    skill_key: str,
) -> str:
    marker = f"## {name}\n"
    if marker not in body:
        raise SkillDefinitionError(f"Skill 缺少 {name} 段: {skill_key}")
    value = body.split(marker, maxsplit=1)[1]
    if next_name:
        next_marker = f"## {next_name}\n"
        if next_marker not in value:
            raise SkillDefinitionError(f"Skill 缺少 {next_name} 段: {skill_key}")
        value = value.split(next_marker, maxsplit=1)[0]
    value = value.strip()
    if not value:
        raise SkillDefinitionError(f"Skill {name} 段为空: {skill_key}")
    return value
