# crypto/executor.py
import asyncio
from datetime import datetime, timezone
from crypto.arbitrage import ArbitrageOpportunity
from crypto.exchanges.base import BaseExchange, ExecutionResult, OrderResult


async def execute(opportunity: ArbitrageOpportunity,
                  buy_ex: BaseExchange,
                  sell_ex: BaseExchange,
                  amount_usdt: float,
                  dry_run: bool = False) -> ExecutionResult:
    """
    Execute both legs simultaneously. In dry_run, simulate fills at opportunity prices.
    Single-leg failures: logged in result, no hedge, no retry.
    """
    now = datetime.now(timezone.utc)

    if dry_run:
        base_buy  = amount_usdt / opportunity.buy_price
        base_sell = amount_usdt / opportunity.sell_price
        buy_result = OrderResult(
            success=True, exchange=buy_ex.name, pair=opportunity.pair, side="buy",
            filled_price=opportunity.buy_price, filled_amount=base_buy)
        sell_result = OrderResult(
            success=True, exchange=sell_ex.name, pair=opportunity.pair, side="sell",
            filled_price=opportunity.sell_price, filled_amount=base_sell)
    else:
        raw = await asyncio.gather(
            buy_ex.place_market_order(opportunity.pair, "buy",  amount_usdt),
            sell_ex.place_market_order(opportunity.pair, "sell", amount_usdt),
            return_exceptions=True,
        )

        def _to_result(r, side: str, ex: BaseExchange) -> OrderResult:
            if isinstance(r, Exception):
                return OrderResult(success=False, exchange=ex.name,
                                   pair=opportunity.pair, side=side,
                                   filled_price=0.0, filled_amount=0.0,
                                   error_msg=str(r))
            return r

        buy_result  = _to_result(raw[0], "buy",  buy_ex)
        sell_result = _to_result(raw[1], "sell", sell_ex)

    success = buy_result.success and sell_result.success
    pnl = 0.0
    if success:
        matched = min(buy_result.filled_amount, sell_result.filled_amount)
        gross    = (sell_result.filled_price - buy_result.filled_price) * matched
        buy_fee  = buy_ex.taker_fee()  * buy_result.filled_price  * matched
        sell_fee = sell_ex.taker_fee() * sell_result.filled_price * matched
        pnl = gross - buy_fee - sell_fee

    return ExecutionResult(
        opportunity=opportunity,
        buy_result=buy_result,
        sell_result=sell_result,
        amount_usdt=amount_usdt,
        simulated=dry_run,
        executed_at=now,
        realized_pnl_usdt=pnl,
        success=success,
    )
