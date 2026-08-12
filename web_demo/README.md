# AI Investment Copilot Web Demo

独立的中芯国际 2023 年报重大风险流程演示。界面采用“机构投研终端 + 证据链编辑器”视觉语言，不依赖正式 `web/src`。

## 运行

```powershell
npm install
npm run dev
```

开发模式由 `.env.development` 显式启用 `real`，访问本地 FastAPI 与 PostgreSQL。

真实接口联调时创建 `.env.local`：

```text
VITE_DEMO_SCENARIO_MODE=real
VITE_DEMO_THESIS_ID=THS-688981-2023FY
VITE_DEMO_CASE_ID=smic-2023-risk
VITE_DEMO_API_PREFIX=/api
```

正式演示与验收必须使用 `real`；上传文件固定为 `smic_2023_annual_report.pdf`（《中芯国际 2023 年年度报告》），证券为 `688981.SH`。资料、证据、关系、建议与时间线均来自实际接口和 PostgreSQL，前端不使用 Mock，也不会在真实模式下用伪造 fallback 补齐业务结果。

同一份年报用于验证三项失效条件：营业收入同比 `< 0`、毛利率 `< 25%`、产能利用率 `< 80%`。程序据此生成“重大风险”状态候选，但不会直接改变正式状态；负责人必须显式选择接受、拒绝或修改并填写理由。接受后状态由“验证中”变为“重大风险”，修改时可选择其他合法状态。

## 路由

- `/theses/:thesisId`
- `/theses/:thesisId/upload`
- `/evidence/:evidenceId/analysis?thesisId=...&relationId=...`
- `/theses/:thesisId/decision`
- `/theses/:thesisId/timeline`

## 视觉编码

- 来源事实：中性白
- 预置 AI 候选：紫色
- 程序计算：青色
- 人工确认：琥珀色

页面始终区分事实与推断，AI 候选不会直接改变关系或投资逻辑状态。
