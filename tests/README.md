# tests — 测试分层

主要维护：谁改代码谁补测试；分层约定属架构方向

```
tests/
├── unit/         纯函数，不碰 IO
├── integration/  需要数据库或外部依赖
├── contract/     校验实现与 contracts/ 一致
└── fixtures/     共享夹具
```

## 分层标准

| 层 | 判断标准 | CI |
| --- | --- | --- |
| `unit/` | 不连数据库、不发网络请求、不读大文件。毫秒级 | 每个 PR 必跑 |
| `integration/` | 需要 PostgreSQL 或队列 | 每个 PR 必跑（CI 起服务） |
| `contract/` | 断言输出符合 JSON Schema / OpenAPI | 每个 PR 必跑 |

`make test` 跑 unit + contract，本地无需数据库。`make test-integration` 跑集成测试。

按模块建子目录：`tests/unit/calc/`、`tests/integration/services/`，与 `app/` 结构对应，便于按 CODEOWNERS 归属。

## 必须有的测试

这些对应产品红线，缺失视为缺陷：

**规则计算（`unit/calc/`）**
- 每个阈值函数覆盖四种情形：达到、接近、未达到、数据缺失
- 口径不一致（单位/报告期/版本）抛 `CalibrationConflictError`
- 用样例包数据断言 H2 不被误判失效（建立日裁剪的守门测试）
- `Decimal` 结果无浮点残留

**人工闸门（`unit/services/`、`integration/services/`）**
- 状态建议不会自动改 `thesis.status`
- 缺 `reason` 的状态变更被拒绝
- worker 无法把证据推进到"已确认"

**权限（`integration/services/`、`integration/api/`）**
- 证据可见性高于来源文档时写入被拒绝
- 无权限访问返回 404 而非 403
- 管理员权限不等于内容访问权

**时间语义（`unit/core/`）**
- naive datetime 入库被拒绝
- 泄露判定边界：披露时间等于生成时间不算泄露
- 跨时区取日历日不错位

**版本与审计（`integration/services/`）**
- 版本快照生成后不可修改
- 审计写入失败时业务动作回滚
- 迁移往返：`upgrade head` 后 `downgrade base` 无残留

**AI 降级（`unit/ai/`、`contract/`）**
- 低于 `low_confidence_cutoff` 的输出标低置信、不触发重大风险提醒
- 输出不符合 Schema 时标 `解析失败` 并进人工队列，不抛给用户

## 夹具

`fixtures/` 只放**样例包的派生数据**，来源限 `docs/data/数据分析交付包/业务样例包/`，
一律带 `is_illustrative=True`。单元测试不读 `real_data/`：单元测试要能在任何环境
秒级跑完，依赖外部数据集会让它变慢且不稳定。

禁止提交非公开信息、带授权限制的内容（付费数据库导出、研报原文）、个人信息、凭证。
这是合规要求，不是风格偏好。

**公开披露数据是例外**：`real_data/` 下九家上市公司的公告清单、定期报告财务数据与
公开行情自 2026-08-11 起纳入版本控制，见 [ADR-0006](../docs/adr/0006-公开披露数据纳入版本控制.md)。
判断标准是「能否从官方公开渠道免费取得且无使用限制」，不是「是否为真实数据」。
集成测试（`integration/test_industry_case_loop.py`）读这批数据。

## 数据库测试

集成测试需要真实 PostgreSQL，SQLite 不能替代：模型用了 JSONB、`timestamptz`、`CheckConstraint`，SQLite 的行为与之不同，用 SQLite 测出来的"通过"没有意义。

每个测试用独立 schema 或事务回滚保证隔离，不依赖执行顺序。

## 写测试的态度

阈值类逻辑的测试不是覆盖率指标，是产品可靠性的直接组成部分。误报会让研究员停止信任提醒，漏报会造成实际损失。这类分支的测试由改动者自己写，评审者会检查四种情形是否都在。
