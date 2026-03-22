# tests/test_paper.py
import pytest
from orders.paper import PaperBroker

@pytest.fixture
def broker():
    return PaperBroker(initial_capital=1_000_000)

def test_buy_reduces_balance(broker):
    result = broker.buy("2330", qty=1000, price=500.0)
    assert result.success
    # 買入 1000 股 × 500 + 手續費 0.1425% + 滑點 0.1%
    expected_cost = 1000 * 500 * (1 + 0.001) * (1 + 0.001425)
    assert abs(broker.get_balance() - (1_000_000 - expected_cost)) < 1.0

def test_sell_increases_balance(broker):
    broker.buy("2330", qty=1000, price=500.0)
    result = broker.sell("2330", qty=1000, price=550.0)
    assert result.success

def test_sell_fails_when_no_position(broker):
    result = broker.sell("2330", qty=1000, price=500.0)
    assert not result.success
    assert result.error_msg is not None

def test_get_positions_reflects_holdings(broker):
    broker.buy("2330", qty=1000, price=500.0)
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].ticker == "2330"
    assert positions[0].qty == 1000
