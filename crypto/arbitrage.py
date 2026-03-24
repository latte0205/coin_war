from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from crypto.exchanges.base import BaseExchange


@dataclass(frozen=True)
class ArbitrageOpportunity:
    pair: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_pct: float
    detected_at: datetime


def calculate_spread(buy_ex: BaseExchange, sell_ex: BaseExchange, ask: float, bid: float) -> float:
    """Return net spread percentage after taker fees.

    Positive values imply a potentially profitable buy-low / sell-high opportunity.
    """
    if ask <= 0:
        raise ValueError("ask must be positive")
    gross_spread = (bid - ask) / ask
    return gross_spread - buy_ex.taker_fee() - sell_ex.taker_fee()
