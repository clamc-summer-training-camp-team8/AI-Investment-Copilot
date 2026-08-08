"""校验 contracts/ 下 JSON Schema 自身的合法性。

只检查 Schema 是否可被 jsonschema 编译，以及公共必填字段是否齐备。
实现输出与 Schema 的一致性由 tests/contract/ 负责。

用法：python -m scripts.check_contracts
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"

# PRD 10.5 要求模型、提示、检索文档和生成时间均版本化；
# PRD 12.2 要求正式 AI 结论展示模型版本与确认状态。缺任一字段无法满足 DA-AC-07。
REQUIRED_AI_FIELDS = {"model_version", "prompt_version", "generated_at", "ai_status"}


def iter_schemas() -> list[Path]:
    return sorted(CONTRACTS_DIR.rglob("*.schema.json"))


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: JSON 解析失败 {exc}"]

    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        problems.append(f"{path}: Schema 非法 {exc}")

    if path.parent.name == "ai":
        properties = set(schema.get("properties", {}))
        missing = REQUIRED_AI_FIELDS - properties
        if missing:
            problems.append(f"{path}: 缺少版本化字段 {sorted(missing)}")

    return problems


def main() -> int:
    schemas = iter_schemas()
    if not schemas:
        print("contracts/ 下暂无 Schema 文件，跳过校验")
        return 0

    problems = [p for path in schemas for p in check(path)]
    for problem in problems:
        print(problem, file=sys.stderr)

    print(f"检查 {len(schemas)} 个 Schema，发现 {len(problems)} 个问题")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
