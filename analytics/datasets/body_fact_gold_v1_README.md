# 正文事实独立金标 v1

该模板用于第二名标注者独立填写正文级金标。不得从 `app/ingest/facts.py` 的规则、
词表或输出反向生成答案。

必填字段：`document_id`、`locator`、`body_text`、`expected_fact_type`、
`expected_direction`、`annotator`、`annotated_at` 和 `reason`。

第一轮建议覆盖产销数据、定期报告、业绩预告各不少于 20 条，并同时保留不应抽取的
负样本。执行：

```powershell
python -m analytics.evaluation.body_fact_eval analytics/datasets/body_fact_gold_v1.csv
```

空模板退出码为 2，防止尚未标注时被误报为评测通过。
