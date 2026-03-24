from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from crypto.arbitrage import ArbitrageOpportunity, calculate_spread
from crypto.exchanges.base import BaseExchange


class Scanner:
    def __init__(self, exchanges: dict[str, BaseExchange], queue: asyncio.Queue, cfg: dict):
        self._exchanges = exchanges
        self._queue = queue
        self._min_spread = cfg["arbitrage"]["min_spread_pct"]
        self._cooldown_s = cfg["arbitrage"]["cooldown_seconds"]
        self._staleness_s = cfg["arbitrage"]["price_staleness_seconds"]
        self._prices: dict[str, dict[str, tuple[float, float, datetime]]] = {
            name: {} for name in exchanges
        }
        self._cooldowns: dict[tuple[str, str, str], datetime] = {}

    async def run(self) -> None:
        pairs_per_exchange: dict[str, list[str]] = {}
        for name, ex in self._exchanges.items():
            pairs_per_exchange[name] = await ex.get_tradable_pairs()

        if not pairs_per_exchange:
            return

        common = set(next(iter(pairs_per_exchange.values())))
        for pairs in pairs_per_exchange.values():
            common &= set(pairs)
        common_pairs = sorted(common)

        tasks = [
            asyncio.create_task(ex.subscribe_orderbook(common_pairs, self._on_update))
            for ex in self._exchanges.values()
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise

    def set_cooldown(self, pair: str, buy_exchange: str, sell_exchange: str) -> None:
        self._cooldowns[(pair, buy_exchange, sell_exchange)] = datetime.now(timezone.utc)

    def remove_exchange(self, name: str) -> None:
        self._prices.pop(name, None)
        self._exchanges.pop(name, None)

    def _on_update(self, exchange_name: str, pair: str, best_ask: float, best_bid: float) -> None:
        now = datetime.now(timezone.utc)
        if exchange_name not in self._prices:
            return
        self._prices[exchange_name][pair] = (best_ask, best_bid, now)
        self._check_spreads(pair, now)

    def _check_spreads(self, pair: str, now: datetime) -> None:
        fresh_exchanges: list[tuple[str, float, float]] = []
        for name, price_dict in self._prices.items():
            entry = price_dict.get(pair)
            if entry is None:
                continue
            ask, bid, updated_at = entry
            if (now - updated_at).total_seconds() <= self._staleness_s:
                fresh_exchanges.append((name, ask, bid))

        if len(fresh_exchanges) < 2:
            return

        for i, (name_a, ask_a, bid_a) in enumerate(fresh_exchanges):
            for name_b, ask_b, bid_b in fresh_exchanges[i + 1 :]:
                self._evaluate(pair, name_a, ask_a, name_b, bid_b, now)
                self._evaluate(pair, name_b, ask_b, name_a, bid_a, now)

    def _evaluate(self, pair: str, buy_name: str, ask: float, sell_name: str, bid: float, now: datetime) -> None:
        key = (pair, buy_name, sell_name)
        cooldown_at = self._cooldowns.get(key)
        if cooldown_at and (now - cooldown_at).total_seconds() < self._cooldown_s:
            return

        buy_ex = self._exchanges.get(buy_name)
        sell_ex = self._exchanges.get(sell_name)
        if buy_ex is None or sell_ex is None:
            return

        spread = calculate_spread(buy_ex, sell_ex, ask, bid)
        if spread >= self._min_spread:
            opp = ArbitrageOpportunity(
                pair=pair,
                buy_exchange=buy_name,
                sell_exchange=sell_name,
                buy_price=ask,
                sell_price=bid,
                spread_pct=spread,
                detected_at=now,
            )
            self._queue.put_nowait(opp)
            self.set_cooldown(pair, buy_name, sell_name)
