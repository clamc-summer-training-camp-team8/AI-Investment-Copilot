# app/db — 数据资源层

主要维护：逻辑引擎方向（问谁，不是评审权限）
PRD 层级：数据资源层

## 职责

ORM 模型与仓储。全仓唯一允许写 SQL 的地方。

```
db/
├── base.py            声明基类、命名约定、公共列类型
├── models/
│   ├── core.py        八类核心对象 + 产品侧扩展表
│   └── governance.py  版本、状态建议、复核任务、审计、质量结果
└── repositories/      按聚合划分的仓储，SQL 只出现在这里
```

## 数据模型对照

数据分析说明书 T8 定义了八类核心对象，`models/core.py` 全部覆盖，并补充了产品侧需要的表：

| 类别 | 表 |
| --- | --- |
| 说明书八类对象 | `document` `thesis` `hypothesis` `metric` `event` `signal` `outcome` `experiment` |
| 产品侧扩展 | `security` `document_segment` `metric_alias` `hypothesis_metric_map` `metric_observation` `evidence` |
| 治理 | `thesis_version` `status_suggestion_log` `review_task` `audit_log` `data_quality_result` |

## 边界

- 不 import `app.services`、`app.api`、`app.workers`。数据层不感知业务编排。
- 不做权限过滤。权限是业务规则，属于 `app/services`。仓储只接受调用方传入的过滤条件。
- 不做审计写入。审计是业务动作的副作用，由 `app/services` 负责。
- 不在模型里写业务判断。状态机在 `app/services`，阈值规则在 `app/calc`。

## 已在模型层固化的约束

这些约束写在数据库层，是因为它们对应的是不可违反的产品红线，不能只靠应用层自觉：

| 约束 | 实现 | 来源 |
| --- | --- | --- |
| 信号不得早于披露 | `signal` 表 `CheckConstraint("generated_at >= available_at")` | DQ-003 |
| 标签不得早于窗口结束 | `outcome` 表 `no_label_before_window_end` | DQ-006 |
| 文档去重 | `UniqueConstraint("content_hash", "parser_version")` | DQ-002 |
| 事件去重 | `event.fingerprint` 唯一 | FR-R-005 |
| 指标口径版本化 | `metric` 主键为 `(metric_id, version)` | 指标管道要求 |
| 观测值不重复 | `(security_id, metric_id, metric_version, period, data_version)` 唯一 | DQ-004 |
| 版本单调 | `(thesis_id, version)` 唯一 | PRD 5.3 |

所有时间列用 `timezone=True`（`timestamptz`）。naive datetime 由 `app.core.timeutil` 在入库前拦截。

## 需要注意的坑

**指标 ID 双套命名**。交付包里指标字典用 `MET-001~005`，台账与样例 CSV 用 `MET-DEMO-001~003`。`metric_alias` 表存在就是为了解决这个问题。导入数据时必须先解析别名，否则假设—指标映射会断链。

**`is_illustrative` 标记**。样例包全是虚构数据。带此标记的行禁止用于真实投资结论，查询接口需要能按此过滤。新增业务表时考虑是否需要这个字段。

**软删除**。核心对象不做物理删除。已关闭的逻辑走状态而不是删行（PRD 5.2 状态机含"已关闭"）。

## 迁移

见 [`../../alembic/README.md`](../../alembic/README.md)。要点：一个 PR 最多一个 head，`downgrade` 不许留空，口径变更走新版本不原地覆盖。

## 测试

- `tests/unit/db/` 模型定义与约束的声明式检查，不连库。
- `tests/integration/db/` 仓储行为，需要 PostgreSQL。用 JSONB 与 `timestamptz`，SQLite 无法替代。
