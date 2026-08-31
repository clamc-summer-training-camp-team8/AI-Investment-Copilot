"""用最新冻结行情和人工确认信号创建可复算的内部量化验证运行。"""

from __future__ import annotations

import argparse
from decimal import Decimal

from app.calc.portfolio import PortfolioConfig
from app.db.repositories import build_uow
from app.db.session import session_scope
from app.services.quant import run_versioned_portfolio_backtest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", default="MDS-akshare-qfq-tushare120-20260830-v1")
    parser.add_argument("--actor", default="p2-akshare-tushare120-validation")
    args = parser.parse_args()

    with session_scope() as session:
        uow = build_uow(session)
        dataset = uow.quant.get_market_dataset(args.dataset_id)
        if dataset is None:
            raise SystemExit(f"行情数据集尚未登记: {args.dataset_id}")
        signal_sets = uow.quant.list_signal_sets()
        if not signal_sets:
            raise SystemExit("没有冻结人工确认信号集")
        signal_set = signal_sets[0]
        security_ids = tuple(sorted({str(item["security_id"]) for item in signal_set.signals}))
        record = run_versioned_portfolio_backtest(
            uow,
            name="AKShare 主源真实确认信号内部验证",
            market_dataset_id=dataset.dataset_id,
            signal_set_id=signal_set.signal_set_id,
            security_ids=security_ids,
            start=dataset.coverage_start,
            end=dataset.coverage_end,
            config=PortfolioConfig(
                initial_capital=Decimal("1000000"),
                rolling_window_days=60,
                walk_forward_days=20,
                rebalance_days=5,
                transaction_cost_bps=Decimal(10),
                slippage_bps=Decimal(5),
                max_security_weight=Decimal("0.20"),
                max_industry_weight=Decimal("0.40"),
                capacity_participation_rate=Decimal("0.10"),
                neutralize_industry=False,
                neutralize_market_cap=False,
                enforce_capacity=True,
                allow_short=True,
            ),
            requested_by=args.actor,
        )
    metrics = record.result["metrics"]
    diagnostics = record.result["diagnostics"]
    print(
        f"{record.run_id} securities={','.join(security_ids)} "
        f"accepted={diagnostics['accepted_signal_count']} "
        f"return={metrics['total_return']} excess={metrics['excess_return']}"
    )


if __name__ == "__main__":
    main()
