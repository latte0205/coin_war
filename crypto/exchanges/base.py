# crypto/exchanges/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crypto.arbitrage import ArbitrageOpportunity

# Default taker fees per exchange (fraction, not percent)
DEFAULT_FEES: dict[str, float] = {
    "binance":      0.001,
    "okx":          0.001,
    "bybit":        0.001,
    "max":          0.0015,
    "max_exchange": 0.0005,   # keep for backward compat with existing tests
    "bitopro":      0.002,
}

OrderbookCallback = Callable[[str, str, float, float], None]
# args: (exchange_name: str, pair: str, best_ask: float, best_bid: float)


@dataclass
class OrderResult:
    success: bool
    exchange: str
    pair: str
    side: str             # "buy" or "sell"
    filled_price: float   # 0.0 on failure
    filled_amount: float  # base currency units, 0.0 on failure
    error_msg: str = ""


@dataclass
class ExecutionResult:
    opportunity: "ArbitrageOpportunity"
    buy_result: OrderResult
    sell_result: OrderResult
    amount_usdt: float
    simulated: bool
    executed_at: datetime
    realized_pnl_usdt: float
    success: bool

    @property
    def failed(self) -> bool:
        return not self.success


class BaseExchange(ABC):
    name: str
    _fee: float
    _price_cache: dict[str, dict]  # {pair: {"ask": float, "bid": float}}

    def __init__(self, name: str | None = None, taker_fee_override: float | None = None):
        # Support both old-style (name as arg) and new-style (name as class attr)
        if name is not None:
            self.name = name
        self._taker_fee_override = taker_fee_override
        if not hasattr(self, '_price_cache'):
            self._price_cache = {}

    def taker_fee(self) -> float:
        if hasattr(self, '_taker_fee_override') and self._taker_fee_override is not None:
            return float(self._taker_fee_override)
        if hasattr(self, '_fee'):
            return self._fee
        return float(DEFAULT_FEES.get(self.name, 0.001))

    def withdraw_fee(self, asset: str) -> float:
        return 0.0

    def current_price(self, pair: str) -> tuple[float, float] | None:
        entry = self._price_cache.get(pair)
        if entry is None:
            return None
        return entry["ask"], entry["bid"]

    @abstractmethod
    async def get_tradable_pairs(self) -> list[str]:
        """Return canonical pairs (BASE/QUOTE uppercase) available on this exchange."""
        ...

    @abstractmethod
    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None:
        """Start background asyncio.Task for WebSocket; return immediately."""
        ...

    @abstractmethod
    async def get_balance(self, asset: str) -> float:
        """Return available balance for asset (e.g. 'USDT', 'BTC')."""
        ...

    @abstractmethod
    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        """Place market order. amount_usdt is always quote currency."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Cancel WebSocket background task."""
        ...
