# orders/paper.py
import uuid
from orders.base import OrderBase, OrderResult, Position

COMMISSION = 0.001425   # 買賣各 0.1425%
STT = 0.003             # 證交稅 0.3%（僅賣出）
SLIPPAGE = 0.001        # 滑點 0.1%


class PaperBroker(OrderBase):
    def __init__(self, initial_capital: float):
        self._balance = initial_capital
        self._positions: dict[str, Position] = {}

    def buy(self, ticker: str, qty: int, price: float) -> OrderResult:
        fill_price = price * (1 + SLIPPAGE)
        cost = fill_price * qty * (1 + COMMISSION)
        if cost > self._balance:
            return OrderResult(False, "", 0.0, "Insufficient balance")
        self._balance -= cost
        if ticker in self._positions:
            pos = self._positions[ticker]
            total_qty = pos.qty + qty
            avg = (pos.avg_price * pos.qty + fill_price * qty) / total_qty
            self._positions[ticker] = Position(ticker, total_qty, avg)
        else:
            self._positions[ticker] = Position(ticker, qty, fill_price)
        return OrderResult(True, str(uuid.uuid4()), fill_price)

    def sell(self, ticker: str, qty: int, price: float) -> OrderResult:
        if ticker not in self._positions or self._positions[ticker].qty < qty:
            return OrderResult(False, "", 0.0, f"No position for {ticker}")
        fill_price = price * (1 - SLIPPAGE)
        proceeds = fill_price * qty * (1 - COMMISSION - STT)
        self._balance += proceeds
        pos = self._positions[ticker]
        new_qty = pos.qty - qty
        if new_qty == 0:
            del self._positions[ticker]
        else:
            self._positions[ticker] = Position(ticker, new_qty, pos.avg_price)
        return OrderResult(True, str(uuid.uuid4()), fill_price)

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_balance(self) -> float:
        return self._balance
