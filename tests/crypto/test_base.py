import pytest
from crypto.exchanges.base import OrderResult, ExecutionResult, DEFAULT_FEES


def test_order_result_failure_defaults():
    r = OrderResult(success=False, exchange="binance", pair="BTC/USDT",
                    side="buy", filled_price=0.0, filled_amount=0.0,
                    error_msg="timeout")
    assert r.filled_price == 0.0
    assert r.filled_amount == 0.0
    assert r.error_msg == "timeout"


def test_execution_result_failed_property():
    from datetime import datetime, timezone
    from crypto.arbitrage import ArbitrageOpportunity
    buy = OrderResult(success=False, exchange="binance", pair="BTC/USDT",
                      side="buy", filled_price=0.0, filled_amount=0.0)
    sell = OrderResult(success=True, exchange="max", pair="BTC/USDT",
                       side="sell", filled_price=50100.0, filled_amount=0.02)
    opp = ArbitrageOpportunity(pair="BTC/USDT", buy_exchange="binance",
                               sell_exchange="max", buy_price=50000.0,
                               sell_price=50100.0, spread_pct=0.002,
                               detected_at=datetime.now(timezone.utc))
    result = ExecutionResult(opportunity=opp, buy_result=buy, sell_result=sell,
                             amount_usdt=100.0, simulated=False,
                             executed_at=datetime.now(timezone.utc),
                             realized_pnl_usdt=0.0, success=False)
    assert result.failed is True


def test_default_fees_present():
    assert "binance" in DEFAULT_FEES
    assert DEFAULT_FEES["binance"] == 0.001
    assert DEFAULT_FEES["max"] == 0.0015
