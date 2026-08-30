# Graph RAG v5 独立盲测候选池

状态：候选池与模型已冻结，等待专业研究员独立标注。

## 数据规模

- 版本：`graph-relevance-v5-blind`
- 检索截止时间：`2026-08-26T18:00:00+08:00`
- 查询：30 个
- 每查询候选：10 个
- 关系行：300 行
- 公司：9 家
- 唯一候选文档：90 份
- v3/v4 查询复用：0
- v3/v4 候选 URL 复用：0

## 候选池口径

每家公司下的所有查询共享同一组 10 份候选文档，评测范围为
`shared_security_closed_pool`。共享池防止通过候选集合差异泄漏查询相关性；封闭池要求关键词、
BM25、中文向量、Graph 种子、Graph 遍历和最终返回都不能越出当前查询的候选文档白名单。

`query_candidate_pool.csv` 不含任何研究员标签。冻结时会分别生成：

- tuner 包：只含候选题面，不含五个标注字段；
- researcher 包：含空白的相关性等级、路径判断、理由、标注员和标注时间；
- model lock：候选池以及检索、Graph、评测实现的 SHA-256；
- evaluator 包：只在标签回收并通过题面哈希校验后生成。

## 生成与冻结

```powershell
python -m analytics.pipelines.prepare_graph_relevance_v5_pool

python -m analytics.pipelines.graph_relevance_v4 freeze `
  --gold-version graph-relevance-v5-blind `
  --source analytics/datasets/graph-relevance-v5-blind/query_candidate_pool.csv `
  --output-dir outputs/graph-relevance-v5-blind

python -m analytics.pipelines.graph_relevance_v4 lock-model `
  --package-dir outputs/graph-relevance-v5-blind
```

当前候选池 SHA-256：
`d9b27f54d65964cb24a3539c3c3ce16533c8f616b90d7b7f2ff8e8be92782a54`。

## 研究员回收约束

研究员只填写五个标签字段，不得修改冻结题面。回收后按 `关系样本ID` 合并并校验候选池、模型锁
和题面哈希。v5 评测只能执行一次；运行前先写消费预约，异常退出也不能把同一盲测集用于反复
调试。只有 14/14 门禁全部通过，质量中心才允许进入 P1 shadow。

完整研究员交付包位于 `outputs/graph-rag-v5-researcher-package-20260827/`。
