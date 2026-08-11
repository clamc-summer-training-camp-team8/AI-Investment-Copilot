# deploy — 环境编排

主要维护：架构与工程方向（问谁，不是评审权限）

## 环境

| 环境 | 用途 | 数据 |
| --- | --- | --- |
| local | 本地开发 | 样例包虚构数据 |
| pilot | 试点环境 | 真实授权资料 |

PRD 12.2 要求测试与生产隔离。试点环境与本地不共用数据库、不共用对象存储、不共用模型端点。

## 本地起环境

```bash
docker compose -f deploy/docker-compose.local.yml up -d   # PostgreSQL + Redis
make migrate
make seed        # 导入样例包（全部 is_illustrative=true）
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
arq app.workers.settings.WorkerSettings
```

`GET /health` 仅表示 API 进程存活；`GET /health/ready` 会同时检查 PostgreSQL 和 Redis，
任一不可用即返回 503。负载均衡器和部署平台应使用后者作为就绪探针。

不装 Docker 也能开发：`make check` 中的单元与契约测试不需要数据库。集成测试需要。

## 配置

配置走环境变量，由 `app/core/config.py` 的 `Settings` 读取。`.env.example` 是模板，`.env` 不进 git。

需要注意的项：

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 试点环境不得指向本地库 |
| `LLM_PROVIDER` | `local`（规则实现，不外发数据）或 `http`（外部/私有兼容端点） |
| `LLM_ENDPOINT` | OpenAI-compatible Chat Completions HTTPS 地址 |
| `LLM_API_KEY` | 模型端点密钥，只能由密钥管理系统或本地 `.env` 注入 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 单次超时与提供者内有限重试 |
| `LLM_MAX_OUTPUT_TOKENS` | 结构化 JSON 最大输出长度，默认 4096 |
| `LLM_THINKING_MODE` | `enabled` / `disabled`；抽取任务默认关闭 |
| `REDIS_URL` | ARQ 后台任务队列 |
| `AUTH_MODE` | 本地可用 `trusted_headers`；非本地必须为 `jwt` |
| `AUTH_JWT_*` | JWT 签名密钥、算法、issuer、audience 与时钟偏差 |
| `CORS_ORIGINS` | 前端允许来源的 JSON 数组，不使用 `*` |
| `RULE_*` | 规则阈值覆盖，变更需记版本 |

## 模型调用安全

HTTP Provider 可以接入公有云或私有兼容端点。无论端点类型，API Key、提示词和请求体
都不得写入日志；API Key 不能返回前端或保存在数据库中。

## 密钥

不进仓库。本地放 `.env`（已 gitignore），试点环境用机构的密钥管理方式。

`.env.example` 里所有敏感项留空或用明显的占位值，不要放能用的默认凭据。

## 备份与可用性

PRD 12.2：试点月度可用性 ≥ 99.5%，失败任务可重试。

数据库需要定期备份。审计日志与版本快照是可追溯性的载体，丢失等于验收项 DA-AC-07 不成立，备份策略上按最高优先级处理。

## 部署检查清单

上试点前逐项确认：

- [ ] 数据库与本地环境物理隔离
- [ ] `LLM_ENDPOINT` 使用 HTTPS，API Key 仅由服务端环境注入
- [ ] `AUTH_MODE=jwt` 且签名密钥至少 32 字节、令牌包含过期时间
- [ ] `CORS_ORIGINS` 只包含实际前端域名
- [ ] PostgreSQL 迁移往返和 Redis 入队/消费均在目标环境验证
- [ ] `DEBUG=false`
- [ ] 无跳过鉴权的开关处于开启状态
- [ ] 迁移已应用且 `alembic heads` 只有一个
- [ ] 备份任务已配置并验证过一次恢复
- [ ] 样例数据（`is_illustrative=true`）未混入真实数据集
- [ ] 未关闭的数据缺口（GAP-001~005）已在验收结论中披露
