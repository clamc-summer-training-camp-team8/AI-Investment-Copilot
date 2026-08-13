"""安全、可重复地重建中芯国际 2023 年报 Demo 初始状态。"""

from __future__ import annotations

import argparse

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.services.demo import DEMO_CASE_ID, reset_demo_case


def _ensure_demo_database() -> None:
    url = make_url(settings.database_url)
    if settings.env not in {"local", "demo", "test"}:
        raise SystemExit(f"拒绝重置 env={settings.env!r}；仅允许 local/demo/test")
    if url.host not in {"localhost", "127.0.0.1"}:
        raise SystemExit(f"拒绝重置非本机数据库主机：{url.host!r}")
    if url.database not in {"copilot", "copilot_demo", "copilot_test"}:
        raise SystemExit(f"拒绝重置未列入白名单的数据库：{url.database!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=[DEMO_CASE_ID], required=True)
    parser.parse_args()
    _ensure_demo_database()
    result = reset_demo_case()
    print("Demo 固定案例已恢复：")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print(f"入口：http://127.0.0.1:5174/theses/{result['thesis_id']}")


if __name__ == "__main__":
    main()
