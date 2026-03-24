import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from crypto.scanner import Scanner
from crypto.exchanges.simulated import SimulatedExchange


def make_cfg(min_spread=0.001, cooldown=30, staleness=5):
    return {
        "arbitrage": {
            "min_spread_pct": min_spread,
            "cooldown_seconds": cooldown,
            "price_staleness_seconds": staleness,
        }
    }


def test_spread_detected_puts_to_queue():
    queue = asyncio.Queue()
    exchanges = {
        "binance": SimulatedExchange("binance", {"BTC/USDT": (50000.0, 50010.0)}),
        "max_exchange": SimulatedExchange("max_exchange", {"BTC/USDT": (50020.0, 50350.0)}),
    }
    scanner = Scanner(exchanges, queue, make_cfg())

    now = datetime.now(timezone.utc)
    scanner._on_update("binance", "BTC/USDT", 50000.0, 50010.0)
    scanner._on_update("max_exchange", "BTC/USDT", 50020.0, 50300.0)

    opp = queue.get_nowait()
    assert opp.buy_exchange == "binance"
    assert opp.sell_exchange == "max_exchange"
    assert opp.pair == "BTC/USDT"
    assert opp.spread_pct > 0.001


def test_cooldown_blocks_duplicate_signal():
    queue = asyncio.Queue()
    exchanges = {
        "binance": SimulatedExchange("binance", {"BTC/USDT": (50000.0, 50010.0)}),
        "max_exchange": SimulatedExchange("max_exchange", {"BTC/USDT": (50020.0, 50350.0)}),
    }
    scanner = Scanner(exchanges, queue, make_cfg(min_spread=0.001, cooldown=30))

    scanner._on_update("binance", "BTC/USDT", 50000.0, 50010.0)
    scanner._on_update("max_exchange", "BTC/USDT", 50020.0, 50300.0)
    scanner._on_update("binance", "BTC/USDT", 50000.0, 50010.0)
    scanner._on_update("max_exchange", "BTC/USDT", 50020.0, 50300.0)

    assert queue.qsize() == 1


def test_stale_price_is_ignored():
    queue = asyncio.Queue()
    exchanges = {
        "binance": SimulatedExchange("binance", {"BTC/USDT": (50000.0, 50010.0)}),
        "max_exchange": SimulatedExchange("max_exchange", {"BTC/USDT": (50020.0, 50350.0)}),
    }
    scanner = Scanner(exchanges, queue, make_cfg(min_spread=0.001, staleness=1))

    old = datetime.now(timezone.utc) - timedelta(seconds=10)
    scanner._prices["binance"]["BTC/USDT"] = (50000.0, 50010.0, old)
    scanner._check_spreads("BTC/USDT", datetime.now(timezone.utc))

    assert queue.empty()


def test_remove_exchange_removes_active_source():
    queue = asyncio.Queue()
    exchanges = {
        "binance": SimulatedExchange("binance", {"BTC/USDT": (50000.0, 50010.0)}),
        "max_exchange": SimulatedExchange("max_exchange", {"BTC/USDT": (50020.0, 50350.0)}),
    }
    scanner = Scanner(exchanges, queue, make_cfg())
    scanner.remove_exchange("max_exchange")

    scanner._on_update("binance", "BTC/USDT", 50000.0, 50010.0)
    assert queue.empty()


def test_run_subscribes_common_pairs_only():
    async def _run():
        queue = asyncio.Queue()
        ex1 = SimulatedExchange("binance", {"BTC/USDT": (50000.0, 50010.0), "ETH/USDT": (3000.0, 3001.0)})
        ex2 = SimulatedExchange("max_exchange", {"BTC/USDT": (50020.0, 50350.0)})
        scanner = Scanner({"binance": ex1, "max_exchange": ex2}, queue, make_cfg())

        await scanner.run()

        opp = queue.get_nowait()
        assert opp.pair == "BTC/USDT"

    asyncio.run(_run())
