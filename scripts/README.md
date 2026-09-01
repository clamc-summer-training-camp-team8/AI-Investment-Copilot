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
| `asset_inventory.py` | 盘点文档、修订、处理运行、衍生产物和 embedding |
| `backfill_asset_derivatives.py` | 为历史正文追加语义切片、事实与事件运行 |
| `backfill_source_archives.py` | 断点回填历史原件、授权核验 revision 与 archive-only run，只追加不覆盖 |
| `build_quant_market_assets.py` | 从已核验公开行情端点冻结组合行情、交易日历、公司行动登记簿和 SHA-256 清单 |
| `build_akshare_quant_market_assets.py` | 以 AKShare 为主源、按实测权限启用 Tushare 对账/补充并发布不可变行情版本 |
| `probe_tushare_permissions.py` | 从本地密钥安全执行最小接口探测，只输出脱敏权限报告 |
| `refresh_quant_market_data.py` | 探测新交易日，按证券有限重试并生成待人工发布的不可变候选与脱敏告警报告 |
| `refresh_tushare_reference_cache.py` | 每目标交易日最多一次缓存 `daily_basic`，按周缓存年度 `trade_cal`，并维护 SHA-256 状态清单 |
| `seed_quant_product.py` | 登记默认冻结行情，并把数据库中真实人工确认关系按确认时间冻结为研究信号；不回填历史时间 |
| `publish_quant_market_dataset.py` | 按审批编号和 SHA-256 校验或登记候选行情；登记与默认版本切换分离 |
| `apply_relation_review_receipt.py` | 校验复核包全部附件哈希，并由逻辑负责人受控应用外部研究员回执 |
| `freeze_confirmed_relation_signal_set.py` | 按显式行情版本、确认时间截面和预期数量冻结人工确认信号集 |
| `resolve_database_target.py` | 从在线 `DATABASE_URL` 解析备份用户与数据库名，只输出非敏感目标字段 |
| `verify_source_archives.py` | 全量核对对象版本存在性，并确定性抽样下载复算内容 SHA-256 |
| `check_governed_assets.py` | 校验 Graph Snapshot、embedding、词表和金标报告 SHA-256 与保留策略 |
| `rebuild_search_index.py` | 从事实表重建权限感知的切片索引 |
| `build_embeddings.py` | 按版本增量生成 pgvector embedding，不覆盖旧版本 |
| `backup_local.ps1` | 备份 PostgreSQL、对象版本内容及 SHA-256 清单 |
| `restore_drill.ps1` | 在一次性隔离容器恢复数据库并逐项核验对象哈希 |
| `p0_upload_probe.py` | 上传新 TXT 并核验归档、Worker、衍生和召回实链 |

P1 效果基线与 RAG 召回评测入口在 `analytics/evaluation/`，可通过
`make evaluate-p1` 或对应 Python 模块运行；结果写入版本化实验目录。

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

行业数据导入后 `document.content_status=标题索引`，标题切片使用 `content_kind=title_index`
和 `extraction_method=metadata`。即使公开 PDF 已归档，只要还没有新的全文解析运行，内容状态
仍保持“标题索引”，不能因为对象存储里已有 PDF 就自动声称正文已可检索。

历史原件回填先做只读盘点，再执行全量任务：

```powershell
python -m scripts.backfill_source_archives --dry-run
python -m scripts.backfill_source_archives --workers 8 --report .runtime/governance/backfill.json
python -m scripts.asset_inventory
```

允许来源、授权依据和遗留本地文件逐字节哈希映射在 `governance/source-policies.json`。下载失败、
非 PDF、越过授权域名、超限或哈希不符均追加失败运行；修正外部状态后直接重跑，不得删除失败记录。

已归档且授权核验通过的标题索引，可用独立的可恢复任务提升为完整正文：

```powershell
python -m scripts.backfill_title_index_fulltext --dry-run --limit 20
python -m scripts.backfill_title_index_fulltext --workers 3 --batch-size 12 `
  --report .runtime/governance/title-index-fulltext.json
```

任务按文档独立提交事务并自动跳过已提升文档。原有标题片段及其 locator 永久保留，新增正文从
当前最大 ordinal 之后开始；每次成功运行同时写入正文片段、确定性事实、全文索引、审计记录和
“证券主体→当前投资逻辑”运行级关联。该关联不等同于证据—假设判断，脚本不会自动创建或确认
正式投资证据。扫描 PDF 默认使用 PDFium + RapidOCR，异常格式页自动降级到 Poppler 多级渲染。

若回填报告确认正文与既有完整文档重复，先用只读模式核验归并条件，再执行受控归并：

```powershell
python -m scripts.merge_duplicate_title_documents <标题索引文档ID> <完整正文文档ID> --dry-run
python -m scripts.merge_duplicate_title_documents <标题索引文档ID> <完整正文文档ID>
```

归并要求双方存在字节一致的活动归档原件，并且失败摄取运行已记录目标重复文档；旧文档只做
软删除，事件、证据定位、证券关系和当前投资逻辑血缘会转移到完整正文。

### P2.1 AKShare 主行情与 Tushare 可选补充

行情构建使用独立最小依赖，建议安装在单独虚拟环境；在线 API 不安装或调用数据供应商 SDK：

```powershell
python -m pip install -r requirements-market-data.txt
python -m scripts.build_akshare_quant_market_assets --start 2023-12-01 --end 2026-08-29 --version akshare-qfq-20260830-v1
python -m scripts.seed_quant_product
python -m scripts.run_quant_product_validation
```

候选版本发布必须先 dry-run，再登记；两个动作都不会切换在线默认版本：

```powershell
python -m scripts.publish_quant_market_dataset `
  --manifest real_data/quant/akshare-qfq-tuaremax10000-20260831-v3/manifest.json `
  --expected-dataset-id MDS-akshare-qfq-tuaremax10000-20260831-v3 `
  --expected-sha256 2d53632169f9fc7156feaaf91c002acea468217c9827917c48b30d0e9b2676db `
  --dry-run

python -m scripts.publish_quant_market_dataset `
  --manifest real_data/quant/akshare-qfq-tuaremax10000-20260831-v3/manifest.json `
  --expected-dataset-id MDS-akshare-qfq-tuaremax10000-20260831-v3 `
  --expected-sha256 2d53632169f9fc7156feaaf91c002acea468217c9827917c48b30d0e9b2676db `
  --register --frozen-by '<审计用户>'
```

只有在候选登记和灰度回测通过后，才允许修改 `QUANT_DEFAULT_MARKET_MANIFEST` 并重建
API/Worker。Catalog 显式返回默认数据集编号；前端不会再把最新登记记录猜成默认版本。

### 专业研究员关系回执与信号集 v2

专业研究员回执不能通过普通 API 倒填研究员和复核时间。先验证回执、候选快照、工作簿与一手
PDF 的逐文件哈希，再由目标逻辑负责人执行；操作人和研究员分别进入审计与关系字段：

```powershell
python -m scripts.apply_relation_review_receipt `
  --receipt outputs/third-a-share-relation-review-20260831/relation_review_receipt.json `
  --expected-receipt-sha256 5b0dd4dd8f98255c29fa364f496922d89a7bd0fc8723da5503c06520ff72b07b `
  --operator analyst-mvp `
  --dry-run

# 仅在目标数据库、操作者与 dry-run 结果均已复核后，把 --dry-run 改为 --apply。
```

信号集冻结必须绑定一个已经登记的行情版本；脚本会要求最新人工确认之后的首个可观察日期落在
行情覆盖内，并显式校验预期信号数和必要关系。v3 截止 2026-08-28，因此不能承接 2026-08-31
形成的第三条人工确认：

```powershell
python -m scripts.freeze_confirmed_relation_signal_set `
  --market-dataset-id '<覆盖 2026-09-01 及之后的候选行情 ID>' `
  --version confirmed-relations-20260901-v2 `
  --as-of '2026-09-01T23:59:59+08:00' `
  --expected-signal-count 3 `
  --required-relation-id REL-ea2dd5a4df3547af `
  --frozen-by '<审计用户>' `
  --dry-run
```

这两个脚本都不切换默认行情版本，也不启动回测。旧 v3、旧信号集和历史运行保持不可变。

默认 AKShare-only 即可冻结。需要 Tushare 补充时，首次或账号权限、积分、SDK、API Origin 发生
变化后执行
最小权限探测；报告会写入被
`.gitignore` 排除的 `.runtime/`，只包含接口状态和脱敏错误：

```powershell
python -m scripts.probe_tushare_permissions --token-file '<本地密钥文件>' --declared-points 120
python -m scripts.build_akshare_quant_market_assets `
  --version akshare-qfq-tushare120-YYYYMMDD-v1 `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-report .runtime/governance/tushare-permission-probe.json
```

也可继续用 `TUSHARE_TOKEN` 环境变量。Token 不写入参数值、日志、数据库或冻结资产。每个版本目录
不可覆盖；AKShare 实际上游、包版本、接口、行数、Tushare 实测权限及降级原因记录在 provenance
与权限快照中，全部资产由清单 SHA-256 校验。120 积分账号的 `trade_cal` 实测有每小时一次频控，
因此主构建不消耗该低频配额；`daily_basic` 也只能由独立低频任务整市场单次获取，禁止主构建
逐证券调用。先刷新参考缓存：

```powershell
python -m scripts.refresh_tushare_reference_cache `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-profile real_data/quant/akshare-qfq-tushare120-20260830-v1/tushare_permission_profile.json
```

缓存位于 `.runtime/quant-reference-cache/`：行情候选只消费状态清单登记且 SHA-256 匹配的文件，
并把实际使用的数据写入候选的 `tushare_reference_snapshot.json`。低频调用不自动重试；同一目标
交易日即使失败也不会重复消耗 `daily_basic` 配额。行情刷新发现新会话时会把候选目标日传给
缓存任务，因此不依赖旧默认版本先完成发布。缓存覆盖不足时市值中性能力继续关闭。

若本地配置采用 Tushare 兼容 API 示例，读取器会同时提取 `token = "..."` 和
`pro._DataApi__http_url = 'https://...'`；自定义地址必须是无路径、用户信息和查询参数的 HTTPS
Origin，且缓存目录会绑定该 Origin，禁止与其他端点混用。10k 权限历史参考回填示例：

```powershell
python -m scripts.refresh_tushare_reference_cache `
  --backfill-history `
  --cache-root .runtime/quant-reference-cache-10000 `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-profile .runtime/governance/tushare-permission-probe-10000.json
```

P2 的 30 只纯 A 股研究池使用独立冻结入口，研究池和前瞻协议随行情一起进入哈希清单：

```powershell
.\.runtime\market-data-venv\Scripts\python.exe -m scripts.build_quant_p2_market_assets `
  --start 2023-12-01 `
  --end 2026-08-31 `
  --version akshare-qfq-p2a30-YYYYMMDD-v1
```

未提供 Tushare 凭证时会生成可开始前瞻积累的 AKShare 候选，但点时市值、涨跌停和双源核验保持
关闭。使用 10k 本地密钥补齐独立缓存后，必须提升数据版本重建，禁止覆盖已有候选：

```powershell
.\.runtime\market-data-venv\Scripts\python.exe -m scripts.backfill_quant_p2_tushare_reference `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-profile .runtime/governance/tushare-permission-probe-10000.json

.\.runtime\market-data-venv\Scripts\python.exe -m scripts.build_quant_p2_market_assets `
  --version akshare-qfq-p2a30-YYYYMMDD-v2 `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-report .runtime/governance/tushare-permission-probe-10000.json `
  --reference-cache-root .runtime/quant-reference-cache-p2-10000
```

当 `stk_limit` 存在已排除停牌、上市初期和除权事件的少量供应端缺口时，可使用已冻结的交易所规则推导资产构建新版本。推导值必须通过前收盘、双源收盘/成交额、价格档位和直接观测不覆盖门禁：

```powershell
.\.runtime\market-data-venv\Scripts\python.exe -m scripts.build_quant_p2_market_assets `
  --version akshare-qfq-tuaremax10000-p2a30-YYYYMMDD-v3 `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-report .runtime/governance/tushare-permission-probe-10000.json `
  --reference-cache-root .runtime/quant-reference-cache-p2-10000 `
  --price-limit-derivations analytics/datasets/quant-p2-a-share-v1/price_limit_derivations.json
```

有效状态完整时 `price_limit_status=true`，但只要存在推导行，
`price_limit_status_fully_observed=false`。日频状态只能支持收盘封板约束，不能声称精确模拟盘中成交。

P2 信号冻结需要同时传入研究池和协议；只有前瞻起点后的人工确认关系会被计数：

```powershell
python -m scripts.freeze_confirmed_relation_signal_set `
  --market-dataset-id '<P2 数据集编号>' `
  --version '<新信号集版本>' `
  --as-of '<带时区截面>' `
  --expected-signal-count '<显式数量>' `
  --research-universe analytics/datasets/quant-p2-a-share-v1/universe.json `
  --sample-protocol analytics/datasets/quant-p2-a-share-v1/protocol.json `
  --frozen-by '<审计用户>' `
  --dry-run
```

工作日 CI 使用仓库 Secret `TUSHARE_TOKEN` 和仓库 Variable `TUSHARE_API_URL`。兼容端点必须单独
登记来源策略，不能标记为 Tushare 官方服务。

交易日刷新入口只创建候选，不修改默认清单或登记数据库。市场无新会话时返回 `noop`：

```powershell
python -m scripts.refresh_quant_market_data `
  --tushare-token-file '<本地密钥文件>' `
  --tushare-permission-report real_data/quant/akshare-qfq-tushare120-20260830-v1/tushare_permission_profile.json `
  --reference-cache-root .runtime/quant-reference-cache
```

报告写入 `.runtime/quant-market-refresh/latest.json` 和不可变的 `runs/QMR-*.json`。工作日 19:30 的
`.github/workflows/quant-market-refresh.yml` 使用同一入口；失败由 CI 状态告警，报告始终上传，只有真实
候选才上传数据目录。候选必须人工复核后再登记为默认版本。

### P1.5 比亚迪（002594）Agent + 人工闭环

只初始化比亚迪数据，不影响数据库里其他证券：

```powershell
python -m alembic upgrade head
python -m scripts.import_industry_dataset --security 002594
```

默认复用已缓存的东方财富财务分片和腾讯行情分片；需要主动刷新时：

```powershell
python -m analytics.pipelines.fetch_financials --security 002594 --refresh
python -m analytics.pipelines.fetch_quotes --refresh
python -m scripts.import_industry_dataset --security 002594
```

启动完整服务后打开 `http://127.0.0.1:5173`。使用 `002594 · 比亚迪` 新建逻辑，
在草稿假设中点击“重新推荐相关指标”，将候选填入人工确认区；同一假设可重复新增
多条指标映射。Agent 只给关联理由、事前阈值依据和数据状态，正式映射、阈值、证据
关系及状态变化都必须由研究员在页面确认。

无需数据库的确定性验收可只跑比亚迪：

```powershell
python -m scripts.run_industry_case --security 002594
```

## seed_sample_pack.py

导入样例包用于本地联调与演示。

两个必须遵守的点：

**全部标记 `is_illustrative=True`。** 样例包是虚构数据，不构成投资建议。混入真实数据集会造成错误结论。

**先解析指标别名。** 交付包存在两套命名：指标字典用 `MET-001~005`，台账与样例 CSV 用 `MET-DEMO-001~003`。必须先写 `metric_alias` 再导观测值，否则假设—指标映射会断链。

另外注意台账 xlsx 的时间是 naive UTC，CSV/JSON 是业务时区，两者有 8 小时偏差。导入时用 `app.core.timeutil.from_naive_utc` 显式转换，不要让 naive datetime 直接入库（`ensure_aware` 会拒绝）。

导入后应能通过这个断言：H2 假设不处于失效状态。样例数据里 2025Q2/Q3 连续两期低于预期，但都早于逻辑建立日 2026-01-15，正确的裁剪逻辑不会判失效。这个断言是 `app/calc` 建立日裁剪逻辑的端到端验证。

## manage_user.py

创建或重置共享环境产品账号。密码默认通过交互式隐藏输入；自动化时只允许从 stdin 传入，避免出现在
进程参数和 shell 历史中。示例：

```bash
printf '%s' '<initial-password>' | python -m scripts.manage_user \
  --user researcher_a \
  --password-stdin \
  --teams research,investment,security-admin
```

账号默认 `must_change_password=true`。初始登录令牌只能访问 `/api/auth/me` 和
`/api/auth/change-password`，完成改密后才可访问业务 API。重置已存在账号也会重新启用首次改密；
除非是受控自动化专用账号，不要使用 `--no-must-change-password`。

## 需要但尚未实现

按优先级：

| 脚本 | 作用 |
| --- | --- |
| `run_quality_rules.py` | 执行 DQ-001~006，结果写 `data_quality_result` |
| `export_audit.py` | 按对象导出审计轨迹，支持 FR-A-003 验收 |
| `check_migration_heads.py` | CI 用，检查 `alembic heads` 只有一个 |
