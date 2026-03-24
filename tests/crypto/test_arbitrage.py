from datetime import datetime, timezone

import pytest

from crypto.arbitrage import ArbitrageOpportunity, calculate_spread
from crypto.exchanges.base import BaseExchange, OrderResult


class DummyExchange(BaseExchange):
    async def get_tradable_pairs(self) -> list[str]:
        return ["BTC/USDT"]

    async def subscribe_orderbook(self, pairs, callback) -> None:
        return None

    async def get_balance(self, asset: str) -> float:
        return 0.0

    async def place_market_order(self, pair, side, amount_usdt):
        return OrderResult(success=False, exchange=self.name, pair=pair,
                           side=side, filled_price=0.0, filled_amount=0.0)

    async def close(self) -> None:
        pass


def test_calculate_spread_profitable():
    buy_ex = DummyExchange("binance")
    sell_ex = DummyExchange("max_exchange")

    result = calculate_spread(buy_ex, sell_ex, ask=50000.0, bid=50300.0)

    assert result == pytest.approx(0.0045)


def test_calculate_spread_not_profitable():
    buy_ex = DummyExchange("binance")
    sell_ex = DummyExchange("okx")

    result = calculate_spread(buy_ex, sell_ex, ask=50000.0, bid=50050.0)

    assert result == pytest.approx(-0.001)


def test_calculate_spread_rejects_invalid_ask():
    buy_ex = DummyExchange("binance")
    sell_ex = DummyExchange("okx")

    with pytest.raises(ValueError):
        calculate_spread(buy_ex, sell_ex, ask=0.0, bid=50050.0)


def test_arbitrage_opportunity_fields():
    now = datetime.now(timezone.utc)
    opp = ArbitrageOpportunity(
        pair="BTC/USDT",
        buy_exchange="binance",
        sell_exchange="max_exchange",
        buy_price=50000.0,
        sell_price=50300.0,
        spread_pct=0.0055,
        detected_at=now,
    )

    assert opp.pair == "BTC/USDT"
    assert opp.buy_exchange == "binance"
    assert opp.sell_exchange == "max_exchange"
    assert opp.spread_pct == pytest.approx(0.0055)
    assert opp.detected_at is now
