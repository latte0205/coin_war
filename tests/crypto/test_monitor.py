import asyncio

import pytest

from crypto.config import enabled_exchange_names


def test_enabled_exchange_names_filters_disabled_entries():
    cfg = {
        "exchanges": {
            "binance": {"enabled": True},
            "okx": {"enabled": False},
            "max_exchange": {"enabled": True},
        }
    }

    assert enabled_exchange_names(cfg) == ["binance", "max_exchange"]


def test_monitor_requires_at_least_two_enabled_exchanges():
    from crypto.monitor import start

    cfg = {
        "exchanges": {
            "binance": {"enabled": True},
            "okx": {"enabled": False},
        }
    }

    with pytest.raises(ValueError, match="need at least 2 enabled exchanges"):
        asyncio.run(start(cfg, dry_run=True))
