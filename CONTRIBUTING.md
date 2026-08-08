# 贡献指南

完整协作规范见 [`docs/collaboration/README.md`](docs/collaboration/README.md)。本文是日常操作的速查表。

## 环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make check
```

## 一次改动的完整流程

```bash
git switch main && git pull --ff-only
git switch -c feat/calc-invalidation-window

# 改代码，写测试

make fmt          # 自动修格式
make check        # 门禁：lint + arch + type + test
git add -p
git commit -m "feat(calc): 按建立日裁剪失效判定窗口

Refs: FR-S-002"
git push -u origin feat/calc-invalidation-window
# 开 PR，填模板，等 CODEOWNERS approve
```

## 提交前自检

- [ ] `make check` 通过
- [ ] 没有绕过人工确认闸门
- [ ] 关键数值由 `app/calc` 计算，不是模型产出
- [ ] 正式结论带原文定位、数据版本、模型版本
- [ ] 没有引入反向模块依赖
- [ ] 阈值逻辑覆盖达到 / 接近 / 未达到 / 数据缺失
- [ ] 改了模块职责就改了对应 README
- [ ] 没提交真实投研数据、密钥、`.env`

## 命令表

| 命令 | 作用 |
| --- | --- |
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

## 分支与提交命名

分支：`<type>/<module>-<slug>`，如 `fix/ingest-pdf-locator`。
提交：`<type>(<module>): <简述>`，正文用 `Refs:` 关联 `FR-*` / `DQ-*` / `GAP-*` 编号。

`type`：`feat` `fix` `refactor` `docs` `test` `chore` `perf`
`module`：`core` `db` `calc` `ingest` `ai` `services` `api` `workers` `analytics` `web` `contracts` `infra`

## 不要做的事

- 不要直接推 `main`。
- 不要开长期功能分支。未完成能力用 `app/core/config.py` 的配置开关藏在主干里，默认关闭。
- 不要在 `app/api` 里直接 import `app.db`。
- 不要在 `app/calc` 里 import 任何兄弟模块。
- 不要在 `analytics/` 里重写一套计算口径，复用 `app.calc`。
- 不要改 `docs/product/`、`docs/data/` 下的需求基线文档，那是产品负责人的领域。
- 不要提交真实投研资料。样例数据仅限 `docs/data/数据分析交付包/业务样例包/`，且带 `is_illustrative` 标记。
