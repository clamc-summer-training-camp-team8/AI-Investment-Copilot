# app/api — HTTP 接口层

负责人：应用接口负责人
PRD 层级：用户交互层

## 职责

HTTP 路由、鉴权、请求校验、响应组装。按 PRD 6.1 的一级导航切分路由：

```
api/
├── main.py            FastAPI 应用装配
└── routers/
    ├── workbench.py   工作台：待确认卡片、待处理变化、复核任务、重大风险
    ├── thesis.py      逻辑卡片：创建、编辑、发布、版本、时间线
    ├── radar.py       变化雷达：候选证据、影响分析、筛选与处置
    ├── review.py      复核中心：任务列表与处置
    └── admin.py       管理：用户角色、模型提示词版本、词典、任务监控
```

## 核心边界：不直连数据库

`.importlinter` 禁止 `app.api` import `app.db`。原因是 PRD 12.1 与 FR-A-003 要求所有内容访问受权限约束并留审计，这两件事都实现在 `app/services`。一旦 API 直接查库，权限过滤与审计留痕会被静默绕过，而这类漏洞在代码评审时很难发现。

正确形态：

```python
from app.services.thesis import list_theses

@router.get("/theses")
def get_theses(q: ThesisQuery, actor: Actor = Depends(current_actor), ...):
    return list_theses(session, actor=actor, filters=q)
```

`actor` 必须传给 services，由 services 决定能看到什么。API 层不自己判断可见性。

## 职责很薄

这一层只做四件事：

1. 解析与校验请求（`app/schemas` 的 Pydantic 模型）
2. 取当前用户身份
3. 调一个 service 函数
4. 组装响应与错误码

不写业务分支。出现 `if` 判断业务状态就是信号：那段逻辑属于 `app/services`。

## 错误码

统一在 `contracts/api/errors.yaml`，前后端共用。至少覆盖 PRD 7.4 的异常流程：

| 情形 | 处理 |
| --- | --- |
| 文档无法解析 | 保留文件，返回失败原因，允许重新上传或转文本 |
| 证券实体歧义 | 返回候选列表要求用户选择，不自动绑定 |
| 模型调用失败 | 返回可重试标识，任务进重试队列 |
| 权限不足 | 不泄露对象是否存在 |

最后一条容易漏：无权限时返回 404 而非 403，否则可以通过枚举 ID 探测他人研究覆盖范围。

## 性能目标（PRD 12.2）

- 列表 P95 ≤ 2 秒
- 详情 P95 ≤ 3 秒

列表接口必须分页，禁止无上限查询。时间线与版本历史按需加载。

## 接口契约

变更接口先改 `contracts/api/`，前端依此开发。破坏性变更需前端负责人 approve，规则见 [ADR-0004](../../docs/adr/0004-契约优先的跨模块协作.md)。

## 认证

MVP 阶段身份可简化（PRD 8.1 对身份系统预留接口）。但即使简化，也必须：

- 每个请求有明确 `actor`，不允许匿名访问业务接口。
- `actor` 一路传到 services 与审计日志。

不要为了本地调试方便留一个跳过鉴权的开关在默认配置里。

## 测试

- `tests/unit/api/` 用假 service 测路由、校验、错误码映射。
- `tests/integration/api/` 端到端，需要数据库。

必须有的测试：无权限访问返回 404 而非 403；列表接口强制分页；未认证请求被拒绝。
