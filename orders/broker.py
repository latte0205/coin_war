# orders/broker.py
import os
from orders.base import OrderBase, OrderResult, Position


class RealBroker(OrderBase):
    """預留真實券商 API 介面（Fubon / 永豐金）。"""
    def __init__(self):
        self._api_key = os.getenv("BROKER_API_KEY", "")
        self._api_secret = os.getenv("BROKER_API_SECRET", "")

    def buy(self, ticker: str, qty: int, price: float) -> OrderResult:
        raise NotImplementedError("Real broker API not yet integrated")

    def sell(self, ticker: str, qty: int, price: float) -> OrderResult:
        raise NotImplementedError("Real broker API not yet integrated")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("Real broker API not yet integrated")

    def get_balance(self) -> float:
        raise NotImplementedError("Real broker API not yet integrated")
