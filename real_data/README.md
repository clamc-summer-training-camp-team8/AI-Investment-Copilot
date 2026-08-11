# real_data — 真实公开披露数据（已纳入版本控制）

本目录自 2026-08-11 起纳入版本控制，见
[ADR-0006](../docs/adr/0006-公开披露数据纳入版本控制.md)。

里面全部是依法强制公开披露的信息：交易所公告清单、定期报告财务数据、公开行情。
任何人都能从原始渠道免费取得。提交它们的目的是**可复算**——团队成员 clone 之后
不需要联网采集就能得到与报告完全相同的数字。采集本身有随机性（行情源限流、公告
接口翻页边界重复），各自跑一遍会得到略有差异的数据，评审时就无法区分「代码变了」
还是「数据变了」。

**这不等于「真实数据都能提交」。** 仍然禁止：非公开信息、带授权限制的内容
（付费数据库导出、研报原文 PDF）、个人信息、用户上传文件、凭证。判断标准是
「能否从官方公开渠道免费取得且无使用限制」。

## 研究范围

三个行业各三家公司，由业务导师指定（GAP-001 的范围问题因此关闭，业务正确性仍待
导师复核）：

| 行业 | 公司 | 市场 | 环节 |
| --- | --- | --- | --- |
| 芯片半导体 | 中芯国际 688981 | A股（科创板） | 晶圆代工 |
| | 兆易创新 603986 | A股 | 存储与 MCU 设计 |
| | 北方华创 002371 | A股 | 半导体设备 |
| 医药 | 恒瑞医药 600276 | A股 | 创新药 |
| | 药明康德 603259 | A股 | 医药研发外包 |
| | 云南白药 000538 | A股 | 中药与健康消费 |
| 新能源汽车 | 比亚迪 002594 | A股 | 整车与动力电池 |
| | 吉利汽车 00175 | **港股** | 整车 |
| | 小鹏汽车 09868 | **港股** | 新势力整车 |

基准按行业取，不共用：半导体→科创50、医药→中证医药、新能源汽车→中证新能源汽车。
跨行业共用一个基准会把行业轮动算成个股 alpha。

## 目录结构

| 路径 | 内容 | 是否进 Git |
| --- | --- | --- |
| `raw/announcements.json` | 3784 条公告清单（标题、披露时间、公告编号、原文链接） | 是 |
| `raw/financials.json` | 九家公司分季度营收与成本，含年报累计值用于交叉校验 | 是 |
| `raw/quotes.json` | 九家公司 + 三个基准的前复权日收盘价 | 是 |
| `dataset/events.csv` | 事件样本与双标注结果 | 是 |
| `dataset/theses.json` | 45 条投资逻辑、135 条核心假设 | 是 |
| `dataset/adjudication_queue.csv` | 待业务裁决的分歧样本 | 是 |
| `dataset/manual_baseline.csv` | 人工基线耗时，**待录入** | 是 |
| `dataset/mentor_blind_annotation.csv` | 59 条盲标（上一轮范围，项目侧试填，非金标） | 是 |
| `dataset/mentor_blind_annotation_v2.csv` | 59 条盲标空白表，`blind-sample-v2-20260811` | 是 |
| `dataset/blind_annotation_result/` | 独立金标回收结果与评测报告 | 是 |
| `reports/` | 闭环、评测、效率三份报告 | 是 |
| `raw/announcements/`、`raw/quotes/` | 采集分片缓存 | 否，中间产物可复原 |
| `*.bak.json` | 上一轮范围的备份快照 | 否 |

根目录的 `documents.txt` / `observations.csv` / `events.csv` 是上一轮单公司案例
（阳光电源）的手工摘录数据，`scripts/run_real_case.py` 仍在用。它们是人工改写的
摘要文本，不是采集产物。

## 数据来源与口径

| 数据 | 来源 | 数据版本 |
| --- | --- | --- |
| 公告清单 | 巨潮资讯网公开检索接口（港股走 `column=hke`） | `cninfo-announcement-v2` |
| 财务数据 | 交易所定期报告，经东财 F10 整理 | `em-f10-gincome-v2` |
| 行情 | 腾讯财经前复权日线 | `tencent-qfq-v1` |

三处必须写明的口径问题：

1. **单季度值是差分出来的，不是披露值。** 交易所披露的是累计值（一季报=Q1、
   中报=H1、三季报=前三季、年报=全年），单季度值由 `Q2=H1−Q1` 这样差分得到。
   缺前一累计期就跳过，不插值。毛利率同样是 `(收入−成本)/收入` 推算值。

2. **港股与 A 股不是同质样本。** 港股用香港会计准则、科目名不同（营运收入 /
   销售成本），且不强制季报——小鹏只有中报与年报，**没有三季报**，因此它的单季度
   指标期数天然少于 A 股公司。这是制度差异，不是数据缺失。

3. **两家港股存在市场错配。** 个股港币计价，基准人民币计价，汇率波动会进入超额
   收益。选中证新能源汽车而不是恒指，是因为它们的经营主体与收入都在境内、行业
   景气度由国内市场决定；恒指是宽基，用它会把港股整体折价当成个股 alpha。
   这个代价必须在报告里写明，不能假装不存在。

口径不同的数字不能混算——这是 DQ-004 与 `CalibrationConflictError` 的存在理由。

## 复现

```bash
# 采集（有网络时；已提交数据的话不需要跑）
python -m analytics.pipelines.fetch_disclosure --start 2024-01-01 --end 2026-08-09 --pages 25
python -m analytics.pipelines.fetch_financials
python -m analytics.pipelines.fetch_quotes --beg 2023-12-01 --end 2026-08-09

# 派生与验证（离线可跑，读已提交的数据）
python -m analytics.pipelines.annotate_events --split-date 2025-10-01
python -m analytics.pipelines.build_theses
PYTHONPATH=. python scripts/run_industry_case.py
python -m analytics.evaluation.run_evaluation
python -m analytics.experiments.run_signal_experiment
```

采集脚本按公司分片缓存，重跑默认复用；要强制重抓加 `--refresh`。

## 免责

数据仅用于系统功能验证，不构成投资建议。系统输出的是候选信号与状态建议，不产生
任何交易、评级或调仓指令。本目录的数据与结论**不支持**「AI 已证明能够稳定创造
Alpha」这类表述。
