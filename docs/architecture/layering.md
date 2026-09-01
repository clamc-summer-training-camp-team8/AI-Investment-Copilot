# 分层依赖契约

本文是 `.importlinter` 配置的说明版本。规则本体在仓库根的 `.importlinter`，由 `make lint-arch` 在本地和 CI 中强制执行。

## 层级顺序

从上到下，上层可依赖下层，下层不得依赖上层：

```
app.api
app.workers
app.services
app.ai | app.collection | app.ingest | app.calc | app.ranking      （同层，互不依赖）
app.db
app.core
```

`app.schemas` 与 `app.api` 同级，供 `app.api` 使用。

## 独立性约束

| 模块 | 禁止 import | 理由 |
| --- | --- | --- |
| `app.calc` | `app.ai`、`app.db`、`app.services`、`app.api`、`app.ingest` | 确定性计算必须可脱库单测、可复算（DA-AC-04） |
| `app.core` | 任何 `app.*` 兄弟模块 | 横切模块被全仓依赖，一旦反向依赖立刻成环 |
| `app.db` | `app.services`、`app.api`、`app.workers` | 数据层不感知业务编排 |
| `app.api` | `app.db` | 绕过 services 会丢掉权限过滤与审计留痕（FR-A-003） |
| `app.*` | `analytics` | 线上代码不依赖离线实验代码 |
| `app.ingest` | `app.ai` | 解析是确定性步骤，不得在解析阶段调模型 |
| `app.collection` | 同层业务模块 | 外部内容采集只负责拉取和规范化，由 workers 编排入库与 AI 分析 |
| `app.ranking` | `app.ai`、`app.db`、`app.services`、`app.api`、`app.workers` | 排序特征与融合公式保持纯函数；模型和持久化由上层适配 |

## 常见违规与正确写法

**违规：在 API 里直接查库**

```python
# app/api/routers/thesis.py
from app.db.models import Thesis          # 禁止
theses = session.query(Thesis).all()
```

正确：经过 services，由 services 负责权限过滤和审计。

```python
# app/api/routers/thesis.py
from app.services.thesis import list_theses
theses = list_theses(session, actor=current_user, filters=q)
```

**违规：在计算模块里读配置默认值以外的东西**

```python
# app/calc/rules.py
from app.db.repositories.evidence import load_confirmed   # 禁止
```

正确：由调用方把数据取好，以数据类传入。`app/calc` 的函数签名应当只含值对象。

**违规：解析阶段调用模型补全字段**

```python
# app/ingest/parsers/pdf.py
from app.ai.providers import complete     # 禁止
```

正确：解析只产出文本与定位，语义抽取由 `app/workers` 在下一步调用 `app/ai`。

## 例外

确实需要例外时，在 `.importlinter` 中显式列出 `ignore_imports` 并写明理由和跟踪项，不允许通过运行时 import 或 `TYPE_CHECKING` 绕过检查。例外条目需架构负责人 approve。
