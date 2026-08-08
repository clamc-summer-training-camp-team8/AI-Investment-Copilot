# 贡献指南

完整协作规范见 [`docs/collaboration/README.md`](docs/collaboration/README.md)。本文是日常操作的速查表。

## 环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

make hooks        # 提交前自动跑门禁，省掉「CI 红了再推一次」
make check
```

## 一次改动的完整流程

```bash
git switch main && git pull --ff-only
git switch -c feat/calc-invalidation-window

# 改代码，写测试

git commit -am "feat(calc): 按建立日裁剪失效判定窗口"   # hook 自动跑门禁
git push -u origin HEAD
# 开 PR → CI 绿 → 自己合
```

**默认不需要任何人 approve。** 只有改 `contracts/`、`alembic/versions/`、`.importlinter`、`docs/product|data/` 时需要 1 个 approve，因为这四类改错了很难回退。

想让人看时在 PR 里 @ 对方，或开 draft PR 讨论。这是主动求助，不是流程义务。

## 提交前只需要自己想清楚的

格式、分层依赖、类型、README 齐备、迁移 head 数量、`.env` 泄露，全部由 `make check` 和 CI 检查，**不用人再核对一遍**。

人要过一遍的只有这五条，因为机器查不了、且事后返工代价高：

- 有没有让 AI 产出直接生效，绕过人工确认？
- 有没有让模型算关键数值（预期差、趋势、同业分位）？
- 正式结论有没有带原文定位、数据版本、模型版本？
- 有没有用到披露日之后才可得的信息？
- 阈值逻辑覆盖了达到 / 接近 / 未达到 / 数据缺失吗？

没碰到的条目不用管。

## 命令表

| 命令 | 作用 |
| --- | --- |
| `make hooks` | 装 pre-commit hook（跳过单次：`git commit --no-verify`）|
| `make fmt` | ruff 自动修复与格式化 |
| `make lint` | ruff 检查 |
| `make lint-arch` | import-linter 分层依赖检查 |
| `make lint-contracts` | `contracts/` 下 Schema 合法性检查 |
| `make type` | mypy 类型检查 |
| `make test` | 单元 + 契约测试 |
| `make test-integration` | 集成测试，需要数据库 |
| `make check` | 上述门禁全跑，等价于 CI |
| `make migrate` | 应用数据库迁移 |
| `make revision m="说明"` | 生成迁移 |

## 命名（建议，不是要求）

分支 `<type>/<module>-<slug>`，如 `fix/ingest-pdf-locator`；提交 `<type>(<module>): <简述>`。

`type`：`feat` `fix` `refactor` `docs` `test` `chore` `perf`
`module`：`core` `db` `calc` `ingest` `ai` `services` `api` `workers` `analytics` `web` `contracts` `infra`

好认而已。起了别的名字不影响合并。涉及验收项时在正文写 `Refs: FR-V-001` 便于追溯，不强求。

## 真正不要做的事

前四条 `make check` 会拦住，列在这里是为了让你知道拦的是什么：

- 不要在 `app/api` 里直接 import `app.db`（绕过 services 会丢权限过滤与审计留痕）。
- 不要在 `app/calc` 里 import 任何兄弟模块（确定性计算必须可脱库复算）。
- 不要在 `analytics/` 里重写一套计算口径，复用 `app.calc`（离线线上算出不同数字最难排查）。
- 不要在 `app/ingest` 解析阶段调模型。

后三条机器拦不住，靠人：

- 不要直接推 `main`。
- 不要开长期功能分支。未完成能力用 `app/core/config.py` 的配置开关藏在主干里，默认关闭。
- 不要提交真实投研资料、密钥、`.env`。样例数据仅限 `docs/data/数据分析交付包/业务样例包/`，且带 `is_illustrative` 标记。
