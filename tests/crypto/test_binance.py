import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from crypto.exchanges.binance import BinanceExchange


def make_cfg(fee_override=None):
    return {"enabled": True, "taker_fee_override": fee_override}


def test_default_fee():
    ex = BinanceExchange(make_cfg())
    assert ex.taker_fee() == 0.001


def test_fee_override():
    ex = BinanceExchange(make_cfg(fee_override=0.0008))
    assert ex.taker_fee() == 0.0008


def test_pair_normalization():
    ex = BinanceExchange(make_cfg())
    assert ex._to_canonical("BTCUSDT") == "BTC/USDT"
    assert ex._to_canonical("ETHUSDT") == "ETH/USDT"
    assert ex._to_canonical("BNBBTC") == "BNB/BTC"


def test_pair_to_binance_symbol():
    ex = BinanceExchange(make_cfg())
    assert ex._to_symbol("BTC/USDT") == "BTCUSDT"
    assert ex._to_symbol("ETH/USDT") == "ETHUSDT"
