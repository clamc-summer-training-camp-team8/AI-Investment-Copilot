"""量化实验室 API 契约与身份边界。"""

from fastapi.testclient import TestClient

from app.api.main import create_app

HEADERS = {"X-User-Id": "quant-researcher"}


def _payload() -> dict[str, object]:
    return {
        "name": "研究事件信号",
        "bars": [
            {"trading_date": "2026-01-02", "close": "100", "benchmark_close": "100"},
            {"trading_date": "2026-01-03", "close": "100", "benchmark_close": "101"},
            {"trading_date": "2026-01-04", "close": "110", "benchmark_close": "102"},
            {"trading_date": "2026-01-05", "close": "121", "benchmark_close": "103"},
        ],
        "signals": [
            {
                "signal_id": "SIG-API-1",
                "disclosed_at": "2026-01-02T09:00:00+08:00",
                "generated_at": "2026-01-02T12:00:00+08:00",
                "direction": "支持",
                "strength": "高",
                "confidence": "1",
            }
        ],
        "config": {
            "initial_capital": "1000",
            "holding_days": 2,
            "transaction_cost_bps": "0",
            "slippage_bps": "0",
            "allow_short": False,
        },
    }


def test_回测返回稳定运行编号和完整指标() -> None:
    with TestClient(create_app()) as client:
        first = client.post("/api/quant/backtests", headers=HEADERS, json=_payload())
        second = client.post("/api/quant/backtests", headers=HEADERS, json=_payload())

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["run_id"].startswith("QBT-")
    assert second.json()["run_id"] == body["run_id"]
    assert body["result"]["methodology_version"] == "event-backtest-v1"
    assert body["result"]["metrics"]["trade_count"] == 1
    assert len(body["result"]["equity_curve"]) == 4


def test_回测禁止匿名调用() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/quant/backtests", json=_payload())
    assert response.status_code == 401


def test_无时区信号被请求校验拒绝() -> None:
    payload = _payload()
    signals = payload["signals"]
    assert isinstance(signals, list)
    assert isinstance(signals[0], dict)
    signals[0]["generated_at"] = "2026-01-02T12:00:00"
    with TestClient(create_app()) as client:
        response = client.post("/api/quant/backtests", headers=HEADERS, json=payload)
    assert response.status_code == 422
