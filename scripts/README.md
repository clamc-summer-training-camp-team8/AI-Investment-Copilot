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
| `export_openapi.py` | 从 FastAPI 路由导出 `contracts/api/openapi.yaml` |
| `import_real_case.py` | 将人工核验后的阳光电源真实公开案例导入联调数据库 |
| `import_industry_dataset.py` | 将 `real_data/` 中已提交的行业公开数据导入本地 PostgreSQL |
| `dev.ps1` | Windows 一键迁移、导入样例和行业联调数据，并启动/停止完整网页服务 |

完整本地网页闭环：

```powershell
.\scripts\dev.ps1 up
# 打开 http://127.0.0.1:5173
.\scripts\dev.ps1 status
.\scripts\dev.ps1 down
```

## 真实案例联调

阳光电源单案例资料不进入仓库。将 `scripts/templates/real_case_sg.template.json`
复制为 `real_data/real_case_sg.json` 后，填写经研究员核验的公开摘录、来源、披露
时间与 `https` 链接，再按以下顺序执行：

```powershell
docker compose -f deploy/docker-compose.local.yml up -d
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.import_real_case
.\.venv\Scripts\python.exe -m scripts.export_openapi
```

导入脚本拒绝缺失事实字段、无时区披露时间和非 `https` 公开链接；它不会读取
`seed_sample_pack.py` 的虚构样例，因此可作为阳光电源前端联调的唯一数据入口。

## 行业公开数据联调

`real_data/dataset/` 与 `real_data/raw/` 已纳入版本控制，包含九家公司的公开公告
索引、财务观测、投资逻辑与人工双标注结果。执行以下命令会导入 45 条逻辑、公告
事件、候选证据和财务观测；重复执行只更新同一数据版本，不会产生重复记录。

```powershell
.\.venv\Scripts\python.exe -m scripts.import_industry_dataset
```

公告正文没有随数据包提交，证据详情中的 `fact_excerpt` 只展示逐字保存的公告标题；
页面必须保留 `source_url` 的公开原文跳转，不能把标题误标为公告正文摘录。

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
