"""导出 OpenAPI 契约到 contracts/api/openapi.yaml。

前端依契约开发、不读后端源码（contracts/api/README.md），所以契约必须是仓库里的
文件而不是靠启服务去 /docs 看——后者要求前端同学先把后端跑起来。

契约由代码生成而不是手写：手写的契约会和实现漂移，而漂移的契约比没有契约更糟，
前端照着它写完才发现对不上。

用法：
    python -m scripts.export_openapi          # 写文件
    python -m scripts.export_openapi --check   # 只校验是否与代码一致（CI 用）
"""

from __future__ import annotations

import argparse
import sys

import yaml

from app.api.main import create_app
from app.core.config import PROJECT_ROOT

DESTINATION = PROJECT_ROOT / "contracts" / "api" / "openapi.yaml"

HEADER = """# 本文件由 scripts/export_openapi.py 生成，请勿手改。
# 改接口请改 app/api，然后运行：make openapi
"""


def render() -> str:
    schema = create_app().openapi()
    body = yaml.safe_dump(schema, allow_unicode=True, sort_keys=True, width=100)
    return HEADER + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只比对不写入。契约与代码不一致时返回非零，供 CI 拦住漂移。",
    )
    args = parser.parse_args()

    rendered = render()
    if args.check:
        if not DESTINATION.exists():
            print(f"契约文件不存在：{DESTINATION}\n运行 make openapi 生成", file=sys.stderr)
            return 1
        if DESTINATION.read_text(encoding="utf-8") != rendered:
            print(
                "契约与代码不一致。接口改了但契约没重新导出，前端会照着过期契约开发。\n"
                "运行 make openapi 更新后再提交。",
                file=sys.stderr,
            )
            return 1
        print("契约与代码一致")
        return 0

    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(rendered, encoding="utf-8")
    paths = create_app().openapi()["paths"]
    print(f"已导出 {len(paths)} 个路径 → {DESTINATION}")
    for path in sorted(paths):
        methods = "、".join(sorted(m.upper() for m in paths[path]))
        print(f"  {methods:12} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
