# orders/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OrderResult:
    success: bool
    order_id: str
    filled_price: float
    error_msg: str | None = None


@dataclass
class Position:
    ticker: str
    qty: int
    avg_price: float


class OrderBase(ABC):
    @abstractmethod
    def buy(self, ticker: str, qty: int, price: float) -> OrderResult: ...

    @abstractmethod
    def sell(self, ticker: str, qty: int, price: float) -> OrderResult: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_balance(self) -> float: ...
