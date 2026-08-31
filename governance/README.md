# 数据资产治理清单

本目录保存会改变数据资产合规边界或可复算性的受控配置。修改后必须同步更新
`asset-integrity-manifest.json`，并由 `.github/CODEOWNERS` 指定的数据维护者复核。

- `source-policies.json`：允许归档的来源、授权依据、核验人和本地遗留文件哈希映射；
- `retention-policy.json`：Graph Snapshot、embedding、词表和金标报告的最低保留规则；
- `asset-integrity-manifest.json`：上述受控资产的文件集合与 SHA-256；
- `embedding-specs/`：已发布 embedding 版本的不可变算法说明。

哈希门禁只证明仓库资产没有静默漂移，不代替来源授权或研究员金标确认。更新受控资产时执行：

```powershell
.\.venv\Scripts\python.exe -m scripts.check_governed_assets --update
.\.venv\Scripts\python.exe -m scripts.check_governed_assets --check
```

历史原件归档使用 `scripts.backfill_source_archives`。成功任务只新增 `document_revision` 和
`ingestion_run`；标题索引仍明确保持为标题索引，直到后续原件解析产生新的完整正文运行。
