# alembic — 数据库迁移

主要维护：逻辑引擎方向
评审：`versions/` 下的改动需 1 个 approve（线上数据改错无法靠回滚代码挽回）

## 命令

```bash
make revision m="新增复核任务优先级字段"   # 生成迁移
make migrate                              # 应用到最新
alembic downgrade -1                      # 回退一步
alembic history                           # 查看链路
alembic heads                             # 检查 head 数量，应为 1
```

## 规则

**一个 PR 最多一个 head。** 两个 PR 同时加迁移时，后合并者负责 rebase 重新生成 revision 链。CI 会检查 `alembic heads` 只有一个。

**`downgrade` 不许留空。** 生成的迁移里 `pass` 要补实现。不可逆的操作（删列、改类型丢精度）需在 PR 里说明，并给出数据备份方案。

**口径变更走新版本，不原地覆盖。** `metric` 表主键是 `(metric_id, version)`，改口径是插新行而不是 UPDATE 旧行。这条来自指标管道要求（说明书 7.2）与 PRD 5.3，违反会破坏历史结论的可复算性。

**审查自动生成的内容。** `--autogenerate` 会漏 JSONB 默认值、`CheckConstraint`、`comment`，也可能把手写索引判为多余而删除。生成后逐行看，不要直接提交。

## 命名

自动生成的 revision id 保留，`message` 用中文描述业务意图：

```
20260808_1530_a1b2c3_新增复核任务优先级字段.py
```

约束与索引命名由 `app/db/base.py` 的 `NAMING_CONVENTION` 统一，不手写名字。

## 数据迁移

结构变更与数据回填分开两个 revision。结构先上，数据回填单独一个，便于失败时只回退一半。

大表回填分批，不在一个事务里更新全表。

## 上线顺序

涉及不兼容变更时按扩展—收缩两步走：

1. 先加新列（可空），代码同时写新旧列。
2. 回填历史数据。
3. 代码切到只读新列。
4. 单独 PR 删旧列。

不要在一个 PR 里同时改结构和切换读写路径。

## 测试

`tests/integration/` 中包含一个迁移往返测试：从空库 `upgrade head`，再 `downgrade base`，断言无残留。这个测试是 `downgrade` 不许留空的执行保障。
