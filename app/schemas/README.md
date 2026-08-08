# app/schemas — API 出入参模型

主要维护：应用接口方向（问谁，不是评审权限）
PRD 层级：用户交互层

## 职责

API 的请求与响应 Pydantic 模型。与 `app/db/models` 的 ORM 模型分开。

建议按对象分文件：`thesis.py`、`hypothesis.py`、`evidence.py`、`event.py`、`review.py`、`common.py`。

## 为什么不直接返回 ORM 模型

三个具体原因：

1. **权限裁剪**。同一条逻辑对不同角色展示的字段不同。ORM 模型没有这个维度。
2. **字段泄露**。ORM 模型会带上内部字段（`content_hash`、`parser_version`、内部 ID）。直接序列化等于把内部结构暴露给前端，也让后续重构受限。
3. **契约稳定**。`contracts/api/` 是前后端约定，不应随数据库结构变动。

## 与 contracts/api 的关系

`contracts/api/` 是契约的事实来源，这里的 Pydantic 模型是它的 Python 实现。两者不一致时以契约为准。

OpenAPI 由 FastAPI 从这些模型生成，生成结果需与 `contracts/api/` 对齐，`tests/contract/` 校验这一点。

## 约定

**校验尽量前置。** 必填、长度、枚举取值在 schema 层拦掉（PRD 7.1 第 4 步「系统执行必填、引用、口径和权限校验」）。业务规则校验（状态流转是否合法、可见性是否越权）留给 `app/services`。

**枚举复用 `app.core.enums`。** 不在 schema 里重复定义中文取值字符串。

**时间字段一律带时区。** 输入的 naive datetime 直接拒绝，错误信息提示需带时区（对应 `app.core.timeutil` 的约束）。

**响应显式声明 AI 状态。** 任何可能包含 AI 产出的响应必须带 `ai_status`、`confirmation_status`、`model_version`、`prompt_version`。PRD 12.2 要求正式 AI 结论展示来源、引用、模型版本和确认状态——前端能展示的前提是接口给了。

**卡片标题长度 120。** 与 `thesis` 表的 `CheckConstraint` 保持一致，两边都要有。

## 边界

- 只 import `app.core`。不 import `app.db`、`app.services`。
- 不写业务逻辑。`validator` 只做格式与取值校验。

## 测试

`tests/unit/schemas/`。重点测：naive datetime 被拒绝、超长标题被拒绝、非法枚举值被拒绝、响应模型不含内部字段。
