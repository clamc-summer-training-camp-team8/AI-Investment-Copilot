"""Deterministic, read-only scenario used for the quant product demo.

The scenario deliberately does not create evidence, relations, signal sets, or
backtest rows in the database.  It combines the configured frozen market data
with an explicitly labelled assumption (all candidate relations were reviewed
and accepted) and runs the production portfolio calculator in memory.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, time
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.calc.portfolio import (
    PortfolioConfig,
    PortfolioSignal,
    run_portfolio_backtest,
)
from app.services.market_data import FrozenJsonMarketData, MarketDataError

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_SCORE_PATTERN: tuple[tuple[str, str, Decimal], ...] = (
    ("支持", "高", Decimal("1.0")),
    ("支持", "中", Decimal("0.7")),
    ("冲突", "低", Decimal("-0.4")),
    ("中性", "中", Decimal("0")),
    ("冲突", "中", Decimal("-0.7")),
)
_SCORE_MAPPING: tuple[tuple[str, str, Decimal], ...] = tuple(
    (direction, strength, sign * weight)
    for direction, sign in (("支持", Decimal(1)), ("冲突", Decimal(-1)))
    for strength, weight in (("高", Decimal(1)), ("中", Decimal("0.7")), ("低", Decimal("0.4")))
) + tuple(("中性", strength, Decimal(0)) for strength in ("高", "中", "低"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _logic_theme(industry: str) -> tuple[str, str]:
    if "半导体" in industry:
        return "国产替代与产品结构兑现", "产能利用、产品结构和客户验证共同支持盈利质量改善"
    if "医药" in industry or "医疗" in industry:
        return "核心产品放量与研发兑现", "核心产品商业化进度与研发里程碑支持中期增长"
    if "汽车" in industry or "电池" in industry:
        return "销量、出海与盈利质量", "产品周期、海外拓展与单位盈利形成可持续增长"
    if "消费" in industry or "食品" in industry:
        return "需求韧性与渠道质量", "终端需求、渠道库存与产品结构支持经营韧性"
    return "经营兑现与竞争优势", "经营指标和行业变化共同检验核心投资假设"


def _mapping_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for direction, strength, score in _SCORE_MAPPING:
        if direction == "中性":
            effect = "本条证据不贡献方向；保留上一有效状态，不触发平仓"
        elif direction == "支持":
            effect = "进入正向排序；绝对值越大，约束前目标权重越高"
        else:
            effect = "进入负向排序；允许做空时形成负暴露，否则降为零"
        rows.append(
            {
                "direction": direction,
                "strength": strength,
                "score": score,
                "portfolio_effect": effect,
            }
        )
    return rows


@lru_cache(maxsize=4)
def build_quant_demo_scenario(manifest_path: Path) -> dict[str, object]:
    """Build a reproducible 30-security assumed-confirmation scenario."""

    resolved_manifest = manifest_path.resolve()
    market_data = FrozenJsonMarketData(resolved_manifest)
    info = market_data.info()
    securities = tuple(info.securities)
    if len(securities) != 30:
        raise MarketDataError(
            f"答辩演示要求恰好 30 只证券；当前冻结数据集为 {len(securities)} 只"
        )

    bars = market_data.bars(securities)
    days = sorted({bar.trading_date for bar in bars})
    checkpoints = days[60:-20:55]
    if len(checkpoints) < 6:
        raise MarketDataError("答辩演示至少需要六个跨期信号截面")

    metadata = {str(item["security_id"]): item for item in market_data.security_metadata()}
    scenario_events: list[dict[str, object]] = []
    engine_signals: list[PortfolioSignal] = []
    for cycle_index, checkpoint in enumerate(checkpoints):
        disclosed_at = datetime.combine(checkpoint, time(9, 0), tzinfo=_SHANGHAI)
        reviewed_at = datetime.combine(checkpoint, time(15, 30), tzinfo=_SHANGHAI)
        for security_index, security_id in enumerate(securities):
            direction, strength, score = _SCORE_PATTERN[(security_index + cycle_index) % len(_SCORE_PATTERN)]
            signal_id = f"DEMO-{checkpoint:%Y%m%d}-{security_id}"
            item = metadata[security_id]
            thesis_title, hypothesis_statement = _logic_theme(str(item["industry"]))
            event = {
                "signal_id": signal_id,
                "security_id": security_id,
                "security_name": item.get("name") or security_id,
                "industry": item["industry"],
                "disclosed_at": disclosed_at,
                "assumed_reviewed_at": reviewed_at,
                "direction": direction,
                "strength": strength,
                "score": score,
                "decision_effect": (
                    "中性留痕 · 组合状态不变"
                    if direction == "中性"
                    else ("正向研究暴露" if score > 0 else "负向研究暴露")
                ),
                "thesis_title": thesis_title,
                "hypothesis_statement": hypothesis_statement,
                "evidence_title": f"{item.get('name') or security_id} · 第 {cycle_index + 1} 期经营与行业变化摘要",
            }
            scenario_events.append(event)
            # Neutral describes this evidence item, not an instruction to flatten an
            # existing position.  It remains in the audit trail but is intentionally
            # not sent as a target-state update to the V3 calculator.
            if score != 0:
                engine_signals.append(
                    PortfolioSignal(
                        signal_id=signal_id,
                        security_id=security_id,
                        disclosed_at=disclosed_at,
                        generated_at=reviewed_at,
                        score=score,
                    )
                )

    config = PortfolioConfig(
        initial_capital=Decimal("1000000"),
        rolling_window_days=120,
        walk_forward_days=40,
        rebalance_days=5,
        transaction_cost_bps=Decimal(10),
        slippage_bps=Decimal(5),
        max_security_weight=Decimal("0.08"),
        max_industry_weight=Decimal("0.40"),
        capacity_participation_rate=Decimal("0.10"),
        neutralize_industry=False,
        neutralize_market_cap=False,
        enforce_capacity=True,
        allow_short=True,
    )
    result = run_portfolio_backtest(bars, engine_signals, config)

    identity_payload = {
        "manifest": info.dataset_id,
        "bars_sha256": info.quote_sha256,
        "policy": "assumed-confirmation-neutral-noop-v1",
        "signals": [
            (event["signal_id"], event["direction"], event["strength"])
            for event in scenario_events
        ],
        "config": _jsonable(asdict(config)),
    }
    digest = sha256(
        json.dumps(identity_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    counts = {
        direction: sum(event["direction"] == direction for event in scenario_events)
        for direction in ("支持", "冲突", "中性")
    }
    latest_events = sorted(
        scenario_events,
        key=lambda item: (item["assumed_reviewed_at"], item["security_id"]),
        reverse=True,
    )[:15]

    return _jsonable(
        {
            "scenario_id": f"QDS-{digest[:20]}",
            "run_id": f"QPF-DEMO-{digest[:16]}",
            "title": "30 证券投资逻辑回测验证 · 全量确认情景",
            "evaluation_track": "scenario_simulation",
            "scenario_policy_version": "assumed-confirmation-neutral-noop-v1",
            "methodology_version": f"{result.methodology_version}+neutral-noop-v1",
            "generated_at": datetime(2026, 9, 2, 16, 0, tzinfo=_SHANGHAI),
            "assumption": "假定研究员对本情景中的 AI 待确认关系逐条核验并全部通过；这些关系仅为演示输入，不写入真实研究库。",
            "disclaimer": "用于验证产品链路与量化方法表达，不是历史真实研究记录，不构成 Alpha 结论、评级、订单或投资建议。",
            "dataset": {
                "dataset_id": info.dataset_id,
                "data_version": info.data_version,
                "manifest_sha256": sha256(resolved_manifest.read_bytes()).hexdigest(),
                "coverage_start": info.coverage_start,
                "coverage_end": info.coverage_end,
                "security_count": len(securities),
                "trading_day_count": len(days),
            },
            "summary": {
                "candidate_count": len(scenario_events),
                "assumed_confirmed_count": len(scenario_events),
                "directional_signal_count": len(engine_signals),
                "neutral_noop_count": counts["中性"],
                "checkpoint_count": len(checkpoints),
                "support_count": counts["支持"],
                "conflict_count": counts["冲突"],
            },
            "score_mapping": _mapping_rows(),
            "decision_pipeline": [
                {"step": "01", "title": "人工确认", "description": "研究员核验 AI 候选与原文、投资假设的关系。"},
                {"step": "02", "title": "事件因子化", "description": "方向给符号，强度给绝对值；AI 置信度不参与权重。"},
                {"step": "03", "title": "组合约束", "description": "横截面归一化后施加单券、行业、容量和可交易性约束。"},
                {"step": "04", "title": "T+1 验证", "description": "仅在确认后的下一可交易日模拟暴露，输出净值、风险和样本外窗口。"},
            ],
            "latest_events": latest_events,
            "result": asdict(result),
        }
    )
