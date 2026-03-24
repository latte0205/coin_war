import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from crypto.arbitrage import ArbitrageOpportunity
from crypto.exchanges.base import OrderResult
from crypto.executor import execute


def _make_opp(buy_price=50000.0, sell_price=50300.0):
    return ArbitrageOpportunity(
        pair="BTC/USDT", buy_exchange="binance", sell_exchange="max",
        buy_price=buy_price, sell_price=sell_price,
        spread_pct=0.0035, detected_at=datetime.now(timezone.utc),
    )


def _make_exchange(name: str, fee: float):
    ex = MagicMock()
    ex.name = name
    ex.taker_fee.return_value = fee
    return ex


@pytest.mark.asyncio
async def test_dry_run_success():
    opp = _make_opp()
    buy_ex = _make_exchange("binance", 0.001)
    sell_ex = _make_exchange("max", 0.0015)
    result = await execute(opp, buy_ex, sell_ex, amount_usdt=100.0, dry_run=True)
    assert result.success is True
    assert result.simulated is True
    assert result.buy_result.filled_price == 50000.0
    assert result.sell_result.filled_price == 50300.0
    # buy filled_amount = 100 / 50000 = 0.002 BTC
    assert abs(result.buy_result.filled_amount - 0.002) < 1e-9
    # sell filled_amount = 100 / 50300
    assert abs(result.sell_result.filled_amount - 100.0 / 50300.0) < 1e-9
    assert result.realized_pnl_usdt > 0


@pytest.mark.asyncio
async def test_real_both_legs_success():
    opp = _make_opp()
    buy_ex = _make_exchange("binance", 0.001)
    sell_ex = _make_exchange("max", 0.0015)
    buy_result = OrderResult(success=True, exchange="binance", pair="BTC/USDT",
                             side="buy", filled_price=50000.0, filled_amount=0.002)
    sell_result = OrderResult(success=True, exchange="max", pair="BTC/USDT",
                              side="sell", filled_price=50300.0, filled_amount=0.002)
    buy_ex.place_market_order = AsyncMock(return_value=buy_result)
    sell_ex.place_market_order = AsyncMock(return_value=sell_result)

    result = await execute(opp, buy_ex, sell_ex, amount_usdt=100.0, dry_run=False)
    assert result.success is True
    assert result.simulated is False
    assert result.realized_pnl_usdt > 0


@pytest.mark.asyncio
async def test_real_buy_leg_fails():
    opp = _make_opp()
    buy_ex = _make_exchange("binance", 0.001)
    sell_ex = _make_exchange("max", 0.0015)
    buy_ex.place_market_order = AsyncMock(side_effect=Exception("timeout"))
    sell_result = OrderResult(success=True, exchange="max", pair="BTC/USDT",
                              side="sell", filled_price=50300.0, filled_amount=0.002)
    sell_ex.place_market_order = AsyncMock(return_value=sell_result)

    result = await execute(opp, buy_ex, sell_ex, amount_usdt=100.0, dry_run=False)
    assert result.success is False
    assert result.buy_result.success is False
    assert result.buy_result.filled_price == 0.0
    assert result.realized_pnl_usdt == 0.0


@pytest.mark.asyncio
async def test_pnl_uses_matched_amount():
    """P&L uses min(buy_filled, sell_filled) to handle partial fills."""
    opp = _make_opp(buy_price=50000.0, sell_price=50300.0)
    buy_ex = _make_exchange("binance", 0.001)
    sell_ex = _make_exchange("max", 0.0015)
    buy_result = OrderResult(success=True, exchange="binance", pair="BTC/USDT",
                             side="buy", filled_price=50000.0, filled_amount=0.002)
    sell_result = OrderResult(success=True, exchange="max", pair="BTC/USDT",
                              side="sell", filled_price=50300.0, filled_amount=0.001)
    buy_ex.place_market_order = AsyncMock(return_value=buy_result)
    sell_ex.place_market_order = AsyncMock(return_value=sell_result)

    result = await execute(opp, buy_ex, sell_ex, amount_usdt=100.0, dry_run=False)
    # matched = min(0.002, 0.001) = 0.001
    expected_gross = (50300.0 - 50000.0) * 0.001  # = 0.30
    expected_fee = 0.001 * 50000.0 * 0.001 + 0.0015 * 50300.0 * 0.001
    expected_pnl = expected_gross - expected_fee
    assert abs(result.realized_pnl_usdt - expected_pnl) < 0.001
