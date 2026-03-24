from __future__ import annotations

import asyncio
from collections.abc import Callable

from crypto.exchanges.base import BaseExchange, OrderResult


class SimulatedExchange(BaseExchange):
    def __init__(
        self,
        name: str,
        quotes: dict[str, tuple[float, float]],
        taker_fee_override: float | None = None,
        delay: float = 0.0,
    ):
        super().__init__(name, taker_fee_override=taker_fee_override)
        self._quotes = quotes
        self._delay = delay

    async def get_tradable_pairs(self) -> list[str]:
        return sorted(self._quotes.keys())

    async def subscribe_orderbook(
        self,
        pairs: list[str],
        callback: Callable[[str, str, float, float], None],
    ) -> None:
        if self._delay:
            await asyncio.sleep(self._delay)
        for pair in pairs:
            if pair in self._quotes:
                ask, bid = self._quotes[pair]
                callback(self.name, pair, ask, bid)
        await asyncio.sleep(0)

    async def get_balance(self, asset: str) -> float:
        return 10000.0

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        ask, bid = self._quotes.get(pair, (0.0, 0.0))
        filled_price = ask if side == "buy" else bid
        filled_amount = amount_usdt / filled_price if filled_price > 0 else 0.0
        return OrderResult(
            success=True,
            exchange=self.name,
            pair=pair,
            side=side,
            filled_price=filled_price,
            filled_amount=filled_amount,
        )

    async def close(self) -> None:
        pass
