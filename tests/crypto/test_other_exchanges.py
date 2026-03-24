import pytest
from crypto.exchanges.okx import OKXExchange
from crypto.exchanges.bybit import BybitExchange
from crypto.exchanges.max_exchange import MAXExchange
from crypto.exchanges.bitopro import BitoproExchange
from crypto.exchanges.base import DEFAULT_FEES


def _cfg(fee=None):
    return {"enabled": True, "taker_fee_override": fee}


# OKX
def test_okx_default_fee():
    assert OKXExchange(_cfg()).taker_fee() == DEFAULT_FEES["okx"]

def test_okx_pair_normalization():
    ex = OKXExchange(_cfg())
    assert ex._to_canonical("BTC-USDT") == "BTC/USDT"

# Bybit
def test_bybit_default_fee():
    assert BybitExchange(_cfg()).taker_fee() == DEFAULT_FEES["bybit"]

def test_bybit_pair_normalization():
    ex = BybitExchange(_cfg())
    assert ex._to_canonical("BTCUSDT") == "BTC/USDT"

# MAX
def test_max_default_fee():
    assert MAXExchange(_cfg()).taker_fee() == DEFAULT_FEES["max"]

def test_max_pair_normalization():
    # MAX uses lowercase e.g. "btcusdt" → "BTC/USDT"
    ex = MAXExchange(_cfg())
    assert ex._to_canonical("btcusdt") == "BTC/USDT"

# BitoPro
def test_bitopro_default_fee():
    assert BitoproExchange(_cfg()).taker_fee() == DEFAULT_FEES["bitopro"]

def test_bitopro_pair_normalization():
    ex = BitoproExchange(_cfg())
    assert ex._to_canonical("BTC_TWD") == "BTC/TWD"
