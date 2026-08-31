"""Generate or verify hashes and retention metadata for governed research assets."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from app.ai.embeddings import EMBEDDING_DIMENSIONS, LOCAL_EMBEDDING_VERSION
from app.core.config import PROJECT_ROOT

POLICY_PATH = PROJECT_ROOT / "governance" / "retention-policy.json"
SOURCE_POLICY_PATH = PROJECT_ROOT / "governance" / "source-policies.json"
MANIFEST_PATH = PROJECT_ROOT / "governance" / "asset-integrity-manifest.json"


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 根节点必须是对象: {path}")
    return payload


def _expected_entries(policy: dict[str, object]) -> list[dict[str, object]]:
    category_policies = policy.get("category_policies")
    asset_sets = policy.get("asset_sets")
    if not isinstance(category_policies, dict) or not isinstance(asset_sets, list):
        raise ValueError("retention-policy 缺少 category_policies 或 asset_sets")
    discovered: dict[str, dict[str, object]] = {}
    for raw in asset_sets:
        if not isinstance(raw, dict):
            raise ValueError("asset_sets 条目必须是对象")
        category = str(raw.get("category", ""))
        category_policy = category_policies.get(category)
        if not isinstance(category_policy, dict):
            raise ValueError(f"资产类别缺少保留策略: {category}")
        if int(category_policy.get("minimum_retention_days", 0)) <= 0:
            raise ValueError(f"资产类别保留天数无效: {category}")
        paths = [str(item) for item in raw.get("paths", [])]
        for pattern in raw.get("globs", []):
            matches = sorted(path for path in PROJECT_ROOT.glob(str(pattern)) if path.is_file())
            if not matches:
                raise ValueError(f"受控资产 glob 没有匹配文件: {pattern}")
            paths.extend(path.relative_to(PROJECT_ROOT).as_posix() for path in matches)
        if not paths:
            raise ValueError(f"资产集合为空: {raw.get('asset_set')}")
        for relative in sorted(set(paths)):
            path = PROJECT_ROOT / relative
            if not path.is_file():
                raise ValueError(f"受控资产不存在: {relative}")
            normalized = path.relative_to(PROJECT_ROOT).as_posix()
            if normalized in discovered:
                raise ValueError(f"受控资产被多个集合重复声明: {normalized}")
            discovered[normalized] = {
                "path": normalized,
                "category": category,
                "asset_set": str(raw.get("asset_set", "")),
                "version": str(raw.get("version", "")),
                "sha256": _digest(path),
                "bytes": path.stat().st_size,
                "minimum_retention_days": int(category_policy["minimum_retention_days"]),
            }
    return [discovered[path] for path in sorted(discovered)]


def _verify_embedding_spec() -> None:
    path = PROJECT_ROOT / "governance" / "embedding-specs" / "hash-char-2gram-v1.json"
    spec = _load_json(path)
    if spec.get("embedding_version") != LOCAL_EMBEDDING_VERSION:
        raise ValueError("embedding 规格版本与代码常量不一致")
    if spec.get("dimensions") != EMBEDDING_DIMENSIONS:
        raise ValueError("embedding 规格维度与代码常量不一致")
    implementation = PROJECT_ROOT / str(spec.get("implementation_path", ""))
    if not implementation.is_file() or spec.get("implementation_sha256") != _digest(implementation):
        raise ValueError("embedding 实现已变化；必须发布新版本，不能静默覆盖旧规格")


def build_manifest() -> dict[str, object]:
    policy = _load_json(POLICY_PATH)
    _verify_embedding_spec()
    return {
        "schema_version": "governed-asset-integrity-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "policy_sha256": _digest(POLICY_PATH),
        "source_policy_sha256": _digest(SOURCE_POLICY_PATH),
        "entries": _expected_entries(policy),
    }


def check() -> list[str]:
    expected = build_manifest()
    actual = _load_json(MANIFEST_PATH)
    errors: list[str] = []
    for key in ("schema_version", "policy_sha256", "source_policy_sha256", "entries"):
        if actual.get(key) != expected.get(key):
            errors.append(f"{key} 与当前受控资产不一致")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    args = parser.parse_args()
    if args.update:
        MANIFEST_PATH.write_text(
            json.dumps(build_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"updated {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")
        return
    errors = check()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    manifest = _load_json(MANIFEST_PATH)
    entries = manifest.get("entries", [])
    print(f"governed asset integrity passed: {len(entries)} files")


if __name__ == "__main__":
    main()
