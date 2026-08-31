"""创建或重置共享环境账号，密码从交互输入或 stdin 获取。"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.services.user_auth import upsert_user


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理 AI Investment Copilot 本地账号")
    parser.add_argument("--user", required=True, help="ASCII 账号 ID")
    parser.add_argument(
        "--teams",
        default="research,investment",
        help="逗号分隔的团队/权限组",
    )
    parser.add_argument("--password-stdin", action="store_true", help="从 stdin 读取密码")
    parser.add_argument("--admin", action="store_true", help="授予系统配置权限")
    parser.add_argument(
        "--no-must-change-password",
        action="store_true",
        help="不要求首次登录改密（默认要求）",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    password = sys.stdin.read().rstrip("\r\n") if args.password_stdin else getpass.getpass()
    identity = upsert_user(
        user_id=args.user,
        password=password,
        teams=args.teams.split(","),
        is_admin=args.admin,
        must_change_password=not args.no_must_change_password,
    )
    print(
        f"账号 {identity.user_id} 已保存；团队={','.join(identity.teams)}；"
        f"首次改密={'是' if identity.must_change_password else '否'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
