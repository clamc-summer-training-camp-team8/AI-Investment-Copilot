# scripts — 开发与运维脚本

主要维护：架构与工程方向（问谁，不是评审权限）

## 约定

- 一个脚本一件事，文件名用动词开头。
- 破坏性操作（清库、删数据）必须要求显式确认参数，不能只靠 `-y`。
- 脚本可 import `app.*`，但不被 `app.*` import。
- 生产环境用的脚本需在 PR 里说明使用场景与回滚方式。

## 现有脚本

| 脚本 | 作用 |
| --- | --- |
| `seed_sample_pack.py` | 导入 `docs/data/数据分析交付包/业务样例包/` 到本地库 |
| `check_contracts.py` | 校验 `contracts/` 下 Schema 自身合法性 |

## seed_sample_pack.py

导入样例包用于本地联调与演示。

两个必须遵守的点：

**全部标记 `is_illustrative=True`。** 样例包是虚构数据，不构成投资建议。混入真实数据集会造成错误结论。

**先解析指标别名。** 交付包存在两套命名：指标字典用 `MET-001~005`，台账与样例 CSV 用 `MET-DEMO-001~003`。必须先写 `metric_alias` 再导观测值，否则假设—指标映射会断链。

另外注意台账 xlsx 的时间是 naive UTC，CSV/JSON 是业务时区，两者有 8 小时偏差。导入时用 `app.core.timeutil.from_naive_utc` 显式转换，不要让 naive datetime 直接入库（`ensure_aware` 会拒绝）。

导入后应能通过这个断言：H2 假设不处于失效状态。样例数据里 2025Q2/Q3 连续两期低于预期，但都早于逻辑建立日 2026-01-15，正确的裁剪逻辑不会判失效。这个断言是 `app/calc` 建立日裁剪逻辑的端到端验证。

## 需要但尚未实现

按优先级：

| 脚本 | 作用 |
| --- | --- |
| `run_quality_rules.py` | 执行 DQ-001~006，结果写 `data_quality_result` |
| `export_audit.py` | 按对象导出审计轨迹，支持 FR-A-003 验收 |
| `check_migration_heads.py` | CI 用，检查 `alembic heads` 只有一个 |
