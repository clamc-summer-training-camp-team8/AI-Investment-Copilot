# contracts/api — HTTP 接口契约

生产方：`app/api`
消费方：`web`

## 内容

| 文件 | 说明 |
| --- | --- |
| `openapi.yaml` | 接口定义。**由 `make openapi` 从 `app/api` 生成，不要手改** |
| `errors.yaml` | 统一错误码表 |

前端依此开发，不读后端源码。接口未就绪时用契约生成 mock。

契约由代码生成而非手写：手写会与实现漂移，而漂移的契约比没有契约更糟——前端照着它
写完才发现对不上。CI 用 `python -m scripts.export_openapi --check` 拦住漂移，
改完接口必须运行 `make openapi` 再提交。

## 已就绪的读接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/workbench` | 工作台：状态概览 + 三类待办 |
| GET | `/api/theses` | 卡片列表，支持状态/标的/负责人/关键词过滤，强制分页 |
| GET | `/api/theses/{id}` | 卡片详情 |
| GET | `/api/theses/{id}/trends` | 按假设的趋势（最近 4-8 期，带口径） |
| GET | `/api/theses/{id}/evidence` | 证据列表 |
| GET | `/api/theses/{id}/suggestions` | 状态建议列表 |
| GET | `/api/theses/{id}/audit` | 留痕，倒序分页 |
| GET | `/api/reviews/adjudications` | 待裁决样本队列 |

## 已就绪的写接口与后台任务

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/theses/drafts` | 创建 AI 候选逻辑草稿 |
| POST | `/api/theses/{id}/publish` | 人工确认并发布草稿 |
| POST | `/api/theses/{id}/status` | 人工确认状态变更 |
| POST | `/api/evidence/{id}/actions` | 确认、驳回或调整证据 |
| POST | `/api/jobs/documents` | 上传文档并进入后台抽取队列 |
| GET | `/api/jobs/{job_id}` | 查询后台任务状态 |
| POST | `/api/reviews` | 创建复核任务 |
| POST | `/api/reviews/{task_id}/resolve` | 解决复核任务 |

## 身份传递

本地开发默认 `AUTH_MODE=trusted_headers`，使用 `X-User-Id` 与 `X-User-Teams`
模拟内网网关身份。试点和生产必须设置 `AUTH_MODE=jwt`，并配置签名密钥、issuer 与
audience；客户端通过 `Authorization: Bearer <token>` 传递身份。非本地环境禁止启用
受信请求头模式。

**`X-User-Id` 必须是 ASCII**（账号 ID 或工号）。HTTP 头按 RFC 7230 只能承载
latin-1，而示例数据里的负责人是「研究员A」这类中文名——中文直接放进请求头，客户端
在编码阶段就会失败，不是服务端返回错误而是请求根本发不出去。中文姓名走展示层查询。

## 路由分组

对齐 PRD 6.1 的一级导航：

```
/api/workbench    工作台
/api/theses       逻辑卡片
/api/radar        变化雷达
/api/reviews      复核中心
/api/admin        管理
```

## 错误码约定

至少覆盖 PRD 7.4 的异常流程：

| 情形 | 状态码 | 要点 |
| --- | --- | --- |
| 文档无法解析 | 422 | 返回失败原因，保留文件，允许重传或转文本 |
| 证券实体歧义 | 409 | 返回候选列表要求用户选择，不自动绑定 |
| 模型调用失败 | 503 | 返回可重试标识 |
| 校验失败 | 400 | 指出具体字段 |
| 未认证 | 401 | |
| 无权限 | **404** | 见下 |

**无权限返回 404 而非 403。** 403 会暴露对象存在性，可以通过枚举 ID 探测他人的研究覆盖范围。研究覆盖本身是敏感信息（PRD 12.1：卡片支持私有 / 团队 / 授权范围）。

## 响应必带的字段

任何可能包含 AI 产出的响应必须带：

```
ai_status              候选 | 低置信 | 解析失败
confirmation_status    待确认 | 已确认 | 已驳回
model_version
prompt_version
evidence_locator       事实类结论必填
```

前端要做到「AI 内容视觉上可区分」，前提是接口给了这些字段。

## 数值字段带口径

指标相关响应必须同时返回口径信息：报告期、`period_type`、单位、`metric_version`、`data_version`、来源文档。

FR-V-001 要求展示口径、报告期、来源和差异。只给一个数字前端无法满足这条。

数值用字符串传 `Decimal`，不用 JSON number。JSON number 在前端会变 IEEE 754 双精度，`-0.02` 可能显示成 `-0.019999999999999997`——样例台账里就有这种残留，不能让它出现在研究员屏幕上。

## 分页

列表接口强制分页，禁止无上限查询。对齐 PRD 12.2 的列表 P95 ≤ 2 秒。

分页参数与响应结构在 `openapi.yaml` 里统一定义，各接口复用。

## 改动流程

本目录下的改动需 1 个 approve。兼容变更（加可选字段、加接口）走个形式即可；破坏性变更（删字段、改类型、改必填性）需新增版本号，并在 PR 里 @ 前端说明迁移窗口。
