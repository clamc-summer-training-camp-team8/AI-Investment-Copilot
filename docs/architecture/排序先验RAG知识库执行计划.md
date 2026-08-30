# 排序先验 RAG 知识库执行计划

## 1. 文档目的

本文定义“带排序先验的 RAG 知识库”的实施范围、数据结构、离线构建流程、在线检索流程、模型检查机制、接口契约、评测方法、开发阶段和验收标准。

本文是 [`AI-Agent-RAG实现规格书.md`](AI-Agent-RAG实现规格书.md) 中 RAG 检索排序能力的专项实施计划，重点解决以下问题：

1. 在关键词与向量相关性之外，引入可解释、可版本化的投研业务排序先验；
2. 对同一公司下的逻辑主题、假设、证据和文档片段建立基础优先级；
3. 在检索时将查询相关性与业务先验融合，返回有序候选；
4. 为未来 GraphRAG 提供稳定的候选重排接口；
5. 在不依赖逐条人工校准的前提下，利用规则、历史数据和高级模型检查员构建试验级排序先验。

## 2. 范围边界

### 2.1 本期包含

- 排序先验知识对象定义；
- 历史数据时间切片；
- 逻辑主题、假设、指标和证据的关联投影；
- 规则特征计算和基础分生成；
- 高级模型排序检查；
- 排序先验版本化落库；
- 关键词、向量和排序先验融合；
- 按场景配置的排序 Profile；
- 带排序解释的统一检索接口；
- 与未来 GraphRAG 对接的候选契约；
- 增量更新、审计、离线评测和灰度切换。

### 2.2 本期不包含

- 主投资逻辑生成 Agent；
- 投资逻辑自动发布；
- GraphRAG 的图构建、图存储和图遍历实现；
- 交易、评级、调仓或组合优化；
- 用市场涨跌直接作为投资逻辑正确性的唯一标签；
- 未经过权限和时间过滤的全库检索；
- 第一版直接训练 Learning-to-Rank 模型。

### 2.3 模块输出

本模块的最终输出是 `RankedRetrievalResult`，而不是投资结论：

```text
查询及过滤条件
  -> 关键词/向量/图候选召回
  -> 排序先验融合
  -> Top-K 有序候选
  -> 分项分数、引用、版本和解释
```

## 3. 已有实现基线

当前项目已具备以下可复用能力：

| 能力 | 现有位置 | 本期复用方式 |
| --- | --- | --- |
| 文档、段落、事实、事件 | `app/db/models/core.py` | 作为知识对象和引用来源 |
| Thesis、Hypothesis、Metric | `app/db/models/core.py` | 作为投研业务先验来源 |
| Evidence、EvidenceRelation | `app/db/models/core.py` | 作为支持/冲突关系来源 |
| 全文索引 | `segment_search_index` | 保留关键词召回 |
| pgvector 向量 | `segment_embedding` | 保留向量召回 |
| 混合检索 | `app/services/assets.py::hybrid_retrieve` | 扩展为先验感知重排 |
| SQL 混合检索 | `app/db/repositories/assets.py::hybrid_search_segments` | 返回分项分数与业务关联 |
| 权限过滤 | `Actor.document_labels` | 必须在排名前过滤 |
| 时间过滤 | `published_from/published_to` | 历史快照和在线检索复用 |
| AI Gateway 与契约校验 | `app/ai/gateway.py`、`contracts/ai/` | 用于排序检查员 |
| AI 调用记录 | `ai_run`、`model_call_log` | 记录检查模型调用和版本 |
| RAG 评测 | `analytics/evaluation/rag_retrieval_eval.py` | 扩展 NDCG、稳定性和消融评测 |

当前混合检索公式为：

```text
retrieval_score = 0.45 * keyword_score + 0.55 * vector_score
```

本期在其后增加排序先验重排。第一版不删除或替换现有检索链路。

## 4. 总体架构

### 4.1 离线先验构建

```text
历史文档、事件、Thesis、Hypothesis、Metric、Evidence
  -> 按公司、方向、期限、as_of 构建时间快照
  -> 业务对象投影与主题归一化
  -> 确定性特征计算
  -> 规则基础分
  -> 高级模型独立检查
  -> 程序门禁
  -> ranking_prior_snapshot / ranking_prior_item
```

### 4.2 在线检索

```text
RankedRetrievalQuery
  -> 权限、证券、行业、方向、期限、as_of 过滤
  -> 关键词/向量召回 Top-N
  -> 可选 GraphRAG 候选合并
  -> 分数归一化
  -> 读取有效排序先验
  -> Ranking Profile 融合
  -> Top-K 排序结果
  -> 检索审计日志
```

### 4.3 关键原则

1. 排序先验是软特征，不作为全库硬召回条件；
2. 查询相关性决定“是否进入候选集”，先验决定“候选集内的业务优先级”；
3. 权限、删除状态和时间窗口必须在打分前过滤；
4. 所有分数先归一化后再融合；
5. 必须返回分项分数，禁止只返回不可解释的总分；
6. 先验、Embedding、检索、检查模型和 Profile 均独立版本化；
7. 模型检查结果不能创建没有引用的新事实；
8. 自动构建结果第一阶段标记为 `provisional`，不冒充人工确认金标。

## 5. 知识对象设计

### 5.1 排序范围键

先验快照使用以下范围键：

```text
security_id + direction + horizon + as_of + ranker_version
```

字段含义：

| 字段 | 说明 |
| --- | --- |
| `security_id` | 证券唯一标识 |
| `direction` | 看多、看空、中性或未指定 |
| `horizon` | 例如 `3M`、`6M`、`12M`、`36M` |
| `as_of` | 快照可见信息截止时间 |
| `ranker_version` | 特征、权重和流程的整体版本 |

第一版只选择一个固定期限和明确方向，降低冷启动复杂度。

### 5.2 排序对象类型

| 对象类型 | 第一版 | 说明 |
| --- | --- | --- |
| `logic_topic` | 必须 | 归一化后的投资驱动主题 |
| `hypothesis` | 必须 | 可证伪的候选假设 |
| `evidence` | 必须 | 支持或冲突证据 |
| `document_segment` | 必须 | RAG 最终返回的引用片段 |
| `metric` | 可选 | 指标本身通常不独立排序，作为假设特征 |
| `graph_path` | 预留 | 未来 GraphRAG 路径候选 |

### 5.3 逻辑主题投影

现有数据库没有独立 `LogicTopic` 实体。第一版可将主题作为排序侧派生对象，不立即改变核心 Thesis 模型：

```json
{
  "topic_id": "TOPIC-<stable-hash>",
  "security_id": "600276.SH",
  "name": "创新药商业化",
  "normalized_statement": "创新药商业化放量是收入增长的重要驱动",
  "aliases": ["创新药放量", "商业化兑现"],
  "direction": "支持",
  "horizon": "12M",
  "hypothesis_ids": ["HYP-001"],
  "metric_ids": ["METRIC-001"],
  "evidence_ids": ["EVD-001"]
}
```

主题 ID 必须由证券、标准表述和版本稳定生成，禁止使用进程随机哈希。

### 5.4 检索文档元数据扩展

排序先验感知的检索候选至少包含：

```json
{
  "document_id": "DOC-001",
  "locator": "DOC-001#paragraph-8",
  "content": "...",
  "security_ids": ["600276.SH"],
  "topic_ids": ["TOPIC-001"],
  "hypothesis_ids": ["HYP-001"],
  "metric_ids": ["METRIC-001"],
  "evidence_relation": "支持",
  "direction": "看多",
  "horizon": "12M",
  "source_type": "公司公告",
  "published_at": "2025-08-20T00:00:00Z",
  "visibility_label": "公开"
}
```

## 6. 数据库设计

### 6.1 `ranking_prior_snapshot`

记录一个范围内的完整先验版本：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `snapshot_id` | varchar PK | 快照 ID |
| `security_id` | varchar | 证券 |
| `direction` | varchar | 方向 |
| `horizon` | varchar | 期限 |
| `as_of` | timestamptz | 信息截止时间 |
| `ranker_version` | varchar | 排序器版本 |
| `feature_version` | varchar | 特征版本 |
| `generator_model_version` | varchar nullable | 初排模型版本 |
| `judge_model_version` | varchar nullable | 检查模型版本 |
| `prompt_version` | varchar nullable | 检查 Prompt 版本 |
| `status` | varchar | generated/validated/provisional/active/superseded/rejected |
| `metadata` | jsonb | 数据量、来源版本、失败信息 |
| `created_at` | timestamptz | 创建时间 |

建议唯一约束：

```text
(security_id, direction, horizon, as_of, ranker_version)
```

### 6.2 `ranking_prior_item`

记录每个对象的分项和最终先验：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `id` | bigint PK | 自增 ID |
| `snapshot_id` | FK | 所属快照 |
| `object_type` | varchar | topic/hypothesis/evidence/document_segment |
| `object_id` | varchar | 对象 ID |
| `base_rank` | integer | 规则初排 |
| `base_score` | numeric | 规则基础分 |
| `judge_rank` | integer nullable | 检查模型排名 |
| `judge_score` | numeric nullable | 检查模型分数 |
| `judge_confidence` | numeric nullable | 检查置信度 |
| `final_rank` | integer | 最终先验排名 |
| `final_score` | numeric | 最终先验分 |
| `feature_scores` | jsonb | 分项特征 |
| `reason_codes` | jsonb | 标准原因码 |
| `citation_locators` | jsonb | 依据引用 |
| `status` | varchar | active/rejected/low_confidence |

建议唯一约束：

```text
(snapshot_id, object_type, object_id)
```

### 6.3 `ranked_retrieval_log`

记录在线检索，支持复现和效果分析：

| 字段 | 说明 |
| --- | --- |
| `query_id` | 查询 ID |
| `query_hash` | 查询文本脱敏哈希 |
| `actor_id` | 调用者 |
| `filters` | 权限以外的业务过滤条件 |
| `retrieval_version` | 检索版本 |
| `embedding_version` | 向量版本 |
| `prior_snapshot_id` | 使用的先验快照 |
| `ranking_profile` | 融合 Profile |
| `candidate_count` | 重排前候选数量 |
| `result_ids` | Top-K 对象及分数 |
| `latency_ms` | 总耗时 |
| `created_at` | 查询时间 |

日志不得保存用户无权查看的候选内容。

## 7. 特征与初始评分

### 7.1 特征分组

#### 业务重要性

- 是否影响收入、利润、现金流或估值；
- 是否为公司核心业务；
- 是否属于目标期限内可兑现的驱动；
- 是否能够解释多个重要指标或假设。

#### 证据质量

- 来源权威性；
- 引用完整性；
- 支持或冲突关系是否直接；
- 是否存在重复来源；
- 是否有人工确认过的关系。

#### 可验证性

- 是否绑定指标；
- 是否存在历史观测；
- 是否可以设置观察窗口；
- 是否具备失效条件。

#### 时间特征

- 信息距 `as_of` 的时间；
- 主题最近更新时间；
- 是否仍在有效期；
- 是否属于一次性事件或持续驱动。

#### 独立性与新颖度

- 与其他主题/假设是否重复；
- 是否只是同一资料的转载；
- 是否引入新的可验证信息。

### 7.2 第一版先验公式

逻辑主题：

```text
topic_prior =
    0.25 * business_materiality
  + 0.15 * evidence_strength
  + 0.15 * persistence
  + 0.15 * verifiability
  + 0.10 * company_specificity
  + 0.10 * causal_strength
  + 0.05 * recency
  + 0.05 * conflict_attention
```

假设：

```text
hypothesis_prior =
    0.25 * causal_strength
  + 0.20 * topic_importance
  + 0.15 * metric_binding
  + 0.15 * falsifiability
  + 0.10 * evidence_quality
  + 0.10 * independence
  + 0.05 * historical_stability
```

证据或文档片段：

```text
evidence_prior =
    0.25 * source_authority
  + 0.20 * direct_relevance
  + 0.15 * completeness
  + 0.15 * temporal_validity
  + 0.10 * novelty
  + 0.10 * traceability
  + 0.05 * statement_clarity
```

### 7.3 支持与冲突分离

禁止将支持与冲突证据简单正负相抵。分别保存：

```text
support_score
conflict_score
uncertainty_score
```

强冲突可能提高主题的关注优先级，而不是使主题消失。

### 7.4 来源权重配置

来源权重必须配置化和版本化，例如：

```yaml
source_authority:
  regulatory_filing: 1.00
  company_annual_report: 0.95
  company_announcement: 0.90
  authorized_research_note: 0.75
  mainstream_news: 0.60
  secondary_reprint: 0.35
```

该配置是可调整的业务规则，不应硬编码在 SQL 中。

## 8. 高级模型检查员

### 8.1 职责

高级模型检查员负责：

- 检查主题或假设是否属于核心经营驱动；
- 检查是否因新闻频率而虚高；
- 检查主题是否重复或存在包含关系；
- 检查期限、方向和公司归属；
- 检查证据是否支持对应特征；
- 检查是否遗漏强冲突证据；
- 独立给出排序、置信度和调整理由。

检查员不负责：

- 修改原始事实；
- 创建无引用的新事实；
- 绕过程序权限；
- 决定正式投资逻辑；
- 替代历史滚动评测。

### 8.2 检查流程

```text
规则初排候选
  -> 隐藏初排解释
  -> 随机化候选展示顺序
  -> 检查模型独立评分
  -> 与初排比较
  -> 对 Top-3 和分数接近项进行成对比较
  -> 输出结构化裁决
```

高价值样本执行两次独立检查；两次候选顺序不同。

### 8.3 输出契约

新增 `contracts/ai/ranking_judgement.schema.json`，核心结构：

```json
{
  "verdict": "accept|adjust|reject",
  "confidence": 0.86,
  "ranking": [
    {
      "object_id": "TOPIC-001",
      "rank": 1,
      "score": 0.91,
      "reason_codes": ["CORE_EARNINGS_DRIVER"],
      "citation_locators": ["DOC-001#paragraph-8"],
      "issues": []
    }
  ],
  "removed_candidates": [],
  "global_issues": [],
  "requires_review": false
}
```

### 8.4 先验融合

第一版建议：

```text
final_prior = 0.70 * rule_prior + 0.30 * judge_score
```

模型检查缺失或失败时，允许保留规则先验，但状态降为 `low_confidence`，不得静默冒充已检查结果。

## 9. 程序门禁

进入 `provisional` 前必须通过：

1. 所有 citation locator 在当前可见数据中存在；
2. 所有资料 `published_at <= as_of`；
3. 证券归属一致或存在已确认关系；
4. 文档未删除、修订未墓碑化；
5. 当前身份具备对应可见性；
6. 分数均在 `[0, 1]`；
7. 对象 ID 在快照内唯一；
8. 检查模型输出符合 JSON Schema；
9. 主题、假设和证据关系无悬空引用；
10. 快照包含特征、Prompt、模型和数据版本。

时间穿越、权限泄漏和引用不存在属于硬失败，不允许降级通过。

## 10. 在线检索与重排

### 10.1 两阶段检索

```text
阶段一：关键词/向量/图召回 Top-N
阶段二：候选集内融合先验，返回 Top-K
```

默认：

```text
N = 50
K = 10
```

先验不得在第一阶段把新主题排除在候选集之外。

### 10.2 分数归一化

所有输入转换到 `[0, 1]`：

```text
keyword_norm
vector_norm
graph_norm
prior_score
```

第一版应评估以下方法后固定一种并版本化：

- 候选集 Min-Max；
- 候选集 Rank Percentile；
- 基于离线分布的分位数映射。

建议第一版使用 Rank Percentile，减少全文分数分布变化的影响；后续再基于评测数据校准。

### 10.3 基础融合

```text
retrieval_score =
    keyword_weight * keyword_norm
  + vector_weight  * vector_norm
  + graph_weight   * graph_norm

final_score =
    relevance_weight * retrieval_score
  + prior_weight     * prior_score
```

当前 `graph_weight = 0`，GraphRAG 接入后再启用。

### 10.4 Ranking Profile

| Profile | 关键词 | 向量 | 图 | 先验 | 适用场景 |
| --- | ---: | ---: | ---: | ---: | --- |
| `document_search` | 0.45 | 0.55 | 0 | 0.10 | 普通资料搜索，先验仅轻度调序 |
| `hypothesis_match` | 0.35 | 0.65 | 0 | 0.25 | 新事件匹配假设 |
| `primary_context` | 0.30 | 0.70 | 0 | 0.40 | 获取公司核心逻辑上下文 |
| `knowledge_browse` | 0.20 | 0.80 | 0 | 0.70 | 弱查询或公司知识浏览 |

表中关键词、向量、图权重用于先计算并归一化 `retrieval_score`；先验权重用于第二层融合。实现时不得把表格中的所有数字直接相加。

Profile 由服务端固定配置，调用方只传 Profile 名称。

### 10.5 高先验低相关保护

满足以下任一条件时，候选不得仅靠先验进入 Top-K：

- 关键词和向量均无有效命中；
- 证券、时间、权限不匹配；
- `retrieval_score` 低于 Profile 最低相关阈值；
- 先验已过期或版本不兼容。

## 11. 接口契约

### 11.1 查询输入

建议新增：

```text
POST /api/retrieval/ranked-search
```

```json
{
  "query": "创新药商业化收入增长",
  "security_ids": ["600276.SH"],
  "industries": [],
  "direction": "看多",
  "horizon": "12M",
  "as_of": "2025-12-31T23:59:59Z",
  "object_types": ["hypothesis", "evidence", "document_segment"],
  "ranking_profile": "primary_context",
  "top_k": 10
}
```

### 11.2 查询输出

```json
{
  "query_id": "RQ-001",
  "retrieval_version": "prior-rag-v1",
  "embedding_version": "hash-char-2gram-v1",
  "prior_snapshot_id": "RPS-001",
  "ranking_profile": "primary_context",
  "items": [
    {
      "object_id": "HYP-001",
      "object_type": "hypothesis",
      "document_id": "DOC-001",
      "locator": "DOC-001#paragraph-8",
      "content": "...",
      "rank": 1,
      "keyword_score": 0.62,
      "vector_score": 0.84,
      "graph_score": null,
      "retrieval_score": 0.76,
      "prior_score": 0.92,
      "final_score": 0.82,
      "feature_scores": {
        "business_materiality": 0.95,
        "evidence_strength": 0.88,
        "verifiability": 1.0
      },
      "reason_codes": ["CORE_EARNINGS_DRIVER"],
      "metadata": {
        "topic_id": "TOPIC-001",
        "direction": "支持",
        "horizon": "12M"
      }
    }
  ]
}
```

## 12. GraphRAG 兼容设计

GraphRAG 模块输出候选时应转换为：

```json
{
  "candidate_id": "HYP-001",
  "object_type": "hypothesis",
  "security_id": "600276.SH",
  "content": "...",
  "graph_score": 0.78,
  "paths": [
    ["EVENT-001", "METRIC-001", "HYP-001"]
  ],
  "locators": ["DOC-001#paragraph-8"],
  "metadata": {}
}
```

排序模块只消费该契约，不依赖图数据库类型和查询语言。GraphRAG 未接入时：

```text
graph_score = null
paths = []
```

GraphRAG 接入后必须重新评测和发布新的 `retrieval_version` 与 Ranking Profile，不能静默改变现有排序口径。

## 13. 离线构建流程

新增脚本：

```text
scripts/build_ranking_priors.py
```

建议参数：

```text
--security-id
--direction
--horizon
--as-of
--ranker-version
--judge-enabled
--dry-run
--output-report
```

执行步骤：

1. 创建或复用快照；
2. 按时间、权限和证券读取知识对象；
3. 投影逻辑主题；
4. 归一化主题和假设；
5. 计算确定性特征；
6. 生成规则初排；
7. 分批调用高级检查模型；
8. 执行成对比较和稳定性检查；
9. 执行程序门禁；
10. 写入快照和先验项；
11. 输出构建报告；
12. 只有完整成功后才将快照切换为 `provisional`。

构建过程必须幂等；相同范围和版本重复执行不能生成冲突数据。

## 14. 增量更新

### 14.1 触发条件

- 新文档完成解析；
- 新事件或新事实落库；
- EvidenceRelation 被确认、修改或解除；
- Hypothesis 或 MetricMapping 修改；
- 文档可见性改变；
- 文档被删除或重新处理；
- 特征或权重版本升级。

### 14.2 更新范围

第一版按公司范围局部重算：

```text
受影响证券 + 方向 + 期限 + 最新 as_of
```

后续再细化到主题或假设级增量。正确性优先于过早优化。

### 14.3 快照切换

```text
active/provisional v1
  -> 构建 v2
  -> 评测 v2
  -> 原子切换 v2
  -> v1 标记 superseded
```

在线请求在一次查询中只能使用一个快照，禁止混合两个先验版本。

## 15. 评测设计

### 15.1 数据切分

严格按时间滚动：

```text
截至 T 的资料 -> 构建 T 时点先验并检索
T 之后资料   -> 仅用于后验评测，不参与构建
```

第一版建议：

- 3 至 5 家公司；
- 每家公司 2 至 4 个历史快照；
- 每个快照 10 至 30 条查询；
- 查询覆盖主题、假设、指标、支持证据和冲突证据。

### 15.2 核心指标

| 指标 | 目的 |
| --- | --- |
| Recall@1/5/10 | 目标对象是否被召回 |
| MRR | 第一个正确结果是否靠前 |
| NDCG@5/10 | 多级相关性排序质量 |
| Top-K 稳定率 | 候选顺序扰动后的稳定性 |
| Prior Lift | 加先验相对基础混合检索的提升 |
| Unauthorized Count | 越权结果，必须为 0 |
| Future Leakage Count | 未来信息泄漏，必须为 0 |
| Citation Validity | locator 存在且内容匹配 |
| Low-Relevance Prior Intrusion | 高先验低相关误入 Top-K |
| P50/P95 Latency | 在线性能 |

### 15.3 消融实验

至少比较：

1. 关键词检索；
2. 当前关键词 + 向量混合检索；
3. 混合检索 + 规则先验；
4. 混合检索 + 规则先验 + 高级模型检查；
5. 未来：混合检索 + GraphRAG + 排序先验。

### 15.4 第一版建议门槛

```text
Unauthorized Count = 0
Future Leakage Count = 0
Citation Validity >= 95%
NDCG@10 不低于当前混合检索
MRR 不低于当前混合检索
Top-5 稳定率 >= 80%
Low-Relevance Prior Intrusion <= 5%
P95 延迟增量 <= 30%
```

如果先验没有带来显著提升，可以保留数据和接口，但默认 Profile 将 `prior_weight` 设为 0，不强行上线。

## 16. 代码结构规划

```text
app/
├── ranking/
│   ├── __init__.py
│   ├── types.py          # 查询、候选、先验、结果类型
│   ├── features.py       # 确定性特征
│   ├── normalizer.py     # 分数归一化
│   ├── scorer.py         # 规则先验与在线融合
│   ├── judge.py          # 高级模型检查适配
│   ├── gates.py          # 时间、引用、权限、结构门禁
│   └── profiles.py       # Ranking Profile 配置
├── services/
│   └── ranked_retrieval.py
├── db/
│   ├── models/ranking.py
│   └── repositories/ranking.py
└── api/routers/retrieval.py

contracts/ai/
└── ranking_judgement.schema.json

scripts/
├── build_ranking_priors.py
└── evaluate_ranked_retrieval.py

analytics/evaluation/
└── ranked_retrieval_eval.py
```

`app/ranking` 不得依赖 `analytics`。在线服务不得读取实验目录中的结果文件。

## 17. 分阶段执行计划

### 阶段 0：契约冻结

任务：

- 明确第一批公司、方向、期限和历史截止日期；
- 定义排序对象；
- 冻结 `RankedRetrievalQuery`、`RankedCandidate`、`RankedRetrievalResult`；
- 冻结 GraphRAG 候选契约；
- 定义分数范围、状态和版本格式。

交付物：

- Python/Pydantic 类型；
- JSON 示例；
- 契约测试。

验收：

- 当前 pgvector 候选和未来 GraphRAG 候选都可转换为统一类型；
- 接口不包含生成 Agent 字段。

### 阶段 1：数据模型与迁移

任务：

- 新增三张排序表；
- 新增 Repository 和 UnitOfWork 端口；
- 增加唯一约束和查询索引；
- 支持快照状态切换。

交付物：

- Alembic 迁移；
- ORM；
- Repository；
- 数据库集成测试。

验收：

- 相同版本幂等写入；
- 查询期间只使用一个快照；
- 旧快照可追溯。

### 阶段 2：规则特征与离线初排

任务：

- 实现来源、时间、证据、指标、独立性等特征；
- 实现第一版规则公式；
- 输出构建报告；
- 对 3 家公司构建历史快照。

交付物：

- `features.py`、`scorer.py`；
- `build_ranking_priors.py`；
- 特征单元测试；
- 样例快照。

验收：

- 同输入和同版本结果确定；
- 每个总分可以由分项复算；
- 无未来资料和越权对象。

### 阶段 3：高级模型检查

任务：

- 新增检查契约；
- 实现候选随机化和独立检查；
- 实现 Top-3/临近候选成对比较；
- 保存调用和置信度；
- 处理超时、无效 JSON 和模型不可用。

交付物：

- `ranking_judgement.schema.json`；
- `judge.py`；
- mock、local、http 测试；
- 检查稳定性报告。

验收：

- 检查失败不会污染已有先验；
- 不存在的引用被程序拒绝；
- 两次检查差异可量化。

### 阶段 4：在线先验重排

任务：

- 扩展当前混合检索返回分项分数；
- 实现分数归一化；
- 实现 Ranking Profile；
- 实现 Top-N 后重排；
- 增加高先验低相关保护。

交付物：

- `ranked_retrieval.py`；
- 检索 API；
- 单元和数据库集成测试。

验收：

- `prior_weight=0` 时结果可退回基础检索；
- 高先验无相关内容不能进入 Top-K；
- 权限和时间过滤在排名前生效。

### 阶段 5：离线评测与灰度

任务：

- 构建时间滚动查询集；
- 实现 NDCG、MRR、稳定率和泄漏指标；
- 完成消融实验；
- 固定 V1 Profile；
- 影子运行并记录延迟。

交付物：

- 评测脚本；
- JSON 结果；
- Markdown 报告；
- 是否启用先验的结论。

验收：

- 权限和时间泄漏为 0；
- 核心排序指标不低于当前基线；
- 性能达到门槛。

### 阶段 6：增量更新与 GraphRAG 接口联调

任务：

- 新资料触发局部先验重算；
- 支持快照原子切换；
- 接收 GraphRAG 候选但保持 `graph_weight=0`；
- 使用固定测试候选验证契约；
- GraphRAG 可用后另发新版本启用图分数。

交付物：

- 增量任务；
- 快照切换测试；
- GraphRAG 契约联调测试。

验收：

- GraphRAG 实现变更不影响排序模块内部结构；
- 未提供图候选时当前检索完全可用；
- 启用图分数必须经过新一轮评测。

## 18. 测试计划

### 18.1 单元测试

- 特征边界；
- 时间衰减；
- 支持与冲突分离；
- 分数归一化；
- Profile 权重；
- 先验缺失和过期；
- 高先验低相关保护；
- 检查模型 Schema 错误；
- 相同输入确定性。

### 18.2 集成测试

- PostgreSQL 快照写入和切换；
- pgvector + 先验联合查询；
- 权限标签过滤；
- 证券、行业和时间过滤；
- 文档删除和可见性改变；
- 新版本与旧版本共存；
- 在线检索日志不含越权内容。

### 18.3 契约测试

- API 与 OpenAPI 一致；
- GraphRAG 候选兼容；
- 高级模型检查输出；
- 版本字段必填；
- 分项分数完整。

## 19. 监控与运行指标

建议记录：

- 每个 Profile 的调用量；
- 基础检索与先验重排的 Top-K 变化率；
- 无先验命中率；
- 过期先验命中率；
- 检查模型成功率和成本；
- P50/P95 检索延迟；
- 越权候选拦截数；
- 未来资料拦截数；
- 重排前后 MRR/NDCG；
- 快照构建耗时和失败原因。

## 20. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 先验压过查询相关性 | 热门主题误入 Top-K | 两阶段检索、最低相关阈值、先验权重上限 |
| 模型自证循环 | 排序看似合理但无外部依据 | 规则初排、独立检查、时间滚动评测、消融实验 |
| 时间穿越 | 历史评测失真 | `as_of` 硬过滤和泄漏测试 |
| 分数量纲不同 | 权重失真 | 统一归一化并版本化 |
| 主题重复 | 先验分散 | 稳定主题 ID、归一化和重复检测 |
| 新主题被旧先验压制 | 无法发现结构性变化 | 先召回后重排，先验不做硬过滤 |
| 来源频率偏置 | 高频新闻虚高 | 来源去重、业务重要性和持续性特征 |
| 高级模型不稳定 | 先验漂移 | 随机顺序双检查、成对比较、保存方差 |
| GraphRAG 接口变化 | 重排模块反复修改 | 固定统一候选契约 |
| 在线性能下降 | P95 超标 | Top-N 控制、批量读先验、缓存有效快照 |

## 21. 第一版完成定义

同时满足以下条件，才视为完成 V1：

- [ ] 排序对象、查询、候选和结果契约已冻结；
- [ ] 排序先验快照和明细可版本化落库；
- [ ] 3 至 5 家公司完成至少 2 个历史快照；
- [ ] 规则先验可以确定性复算；
- [ ] 高级模型检查可以独立运行并结构化记录；
- [ ] 当前关键词/向量检索可接入先验重排；
- [ ] 检索结果返回分项分数、版本和 locator；
- [ ] `prior_weight=0` 可以安全回退到现有混合检索；
- [ ] 权限泄漏和未来信息泄漏均为 0；
- [ ] 完成基线、规则先验和模型检查三组消融实验；
- [ ] NDCG、MRR 和稳定性达到约定门槛；
- [ ] GraphRAG 候选契约已有测试，但不依赖图实现；
- [ ] 文档、脚本、迁移、测试和评测报告齐全；
- [ ] 不包含主逻辑生成 Agent 或自动发布能力。

## 22. 建议立即启动的工作

1. 从现有九公司数据中选择 3 家作为金丝雀样本；
2. 明确第一版统一期限和方向；
3. 冻结四个核心契约；
4. 对现有历史数据做 `as_of` 可用性检查；
5. 创建排序先验数据库迁移设计；
6. 先实现不调用模型的规则基线；
7. 在规则基线稳定后接入高级检查模型；
8. 最后改造在线混合检索，避免同时改数据、模型和在线链路。

四个核心契约为：

```text
RankingPriorSnapshot
RankingPriorItem
RankedRetrievalQuery
RankedRetrievalResult
```

## 23. 待产品与协作方冻结的决策

以下决策不阻塞文档落地，但进入编码阶段前必须冻结：

1. 第一批公司的具体名单；
2. 第一版方向与期限；
3. 来源权威性初始配置；
4. 高级检查模型及调用预算；
5. 自动先验最高状态使用 `provisional` 还是 `active_experimental`；
6. GraphRAG 候选的最终字段名称和对象 ID 规范；
7. V1 的 NDCG、MRR、稳定率和延迟门槛是否采用本文建议值。
