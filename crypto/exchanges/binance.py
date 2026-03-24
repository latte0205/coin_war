# crypto/exchanges/binance.py
"""
Binance exchange adapter.
WebSocket: uses python-binance AsyncClient + BinanceSocketManager for order book streams.
REST: uses python-binance AsyncClient for orders and balance.
"""
import asyncio
import logging
import os
from crypto.exchanges.base import BaseExchange, OrderResult, DEFAULT_FEES, OrderbookCallback

logger = logging.getLogger(__name__)

# Known USDT-quoted pairs for normalization (extend as needed)
_KNOWN_QUOTES = ("USDT", "BTC", "ETH", "BNB", "BUSD")


class BinanceExchange(BaseExchange):
    name = "binance"

    def __init__(self, exchange_cfg: dict):
        self._fee = exchange_cfg.get("taker_fee_override") or DEFAULT_FEES["binance"]
        self._price_cache: dict[str, dict] = {}
        self._ws_task: asyncio.Task | None = None
        self._api_key    = os.getenv("BINANCE_API_KEY", "")
        self._api_secret = os.getenv("BINANCE_API_SECRET", "")

    # ── Symbol conversion ──────────────────────────────────────────────────

    def _to_canonical(self, symbol: str) -> str:
        """'BTCUSDT' → 'BTC/USDT'"""
        for quote in _KNOWN_QUOTES:
            if symbol.endswith(quote):
                base = symbol[: -len(quote)]
                return f"{base}/{quote}"
        # Fallback: split at midpoint
        mid = len(symbol) // 2
        return f"{symbol[:mid]}/{symbol[mid:]}"

    def _to_symbol(self, pair: str) -> str:
        """'BTC/USDT' → 'BTCUSDT'"""
        return pair.replace("/", "")

    # ── BaseExchange interface ─────────────────────────────────────────────

    async def get_tradable_pairs(self) -> list[str]:
        from binance import AsyncClient
        client = await AsyncClient.create(self._api_key, self._api_secret)
        try:
            info = await client.get_exchange_info()
            symbols = [
                self._to_canonical(s["symbol"])
                for s in info["symbols"]
                if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"
            ]
            return symbols
        finally:
            await client.close_connection()

    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None:
        """Start background WebSocket task; return immediately."""
        symbols = [self._to_symbol(p).lower() for p in pairs]
        self._ws_task = asyncio.create_task(
            self._ws_loop(symbols, pairs, callback)
        )

    async def _ws_loop(self, symbols: list[str], pairs: list[str],
                       callback: OrderbookCallback) -> None:
        from binance import AsyncClient
        from binance import BinanceSocketManager
        retries = 0
        delay = 1
        while retries < 5:
            try:
                client = await AsyncClient.create(self._api_key, self._api_secret)
                bm = BinanceSocketManager(client)
                streams = [f"{s}@bookTicker" for s in symbols]
                async with bm.multiplex_socket(streams) as ms:
                    retries = 0
                    delay = 1
                    while True:
                        msg = await ms.recv()
                        data = msg.get("data", {})
                        sym = data.get("s", "")
                        ask = float(data.get("a", 0))
                        bid = float(data.get("b", 0))
                        if sym and ask and bid:
                            pair = self._to_canonical(sym)
                            self._price_cache[pair] = {"ask": ask, "bid": bid}
                            callback(self.name, pair, ask, bid)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"Binance WS error (retry {retries+1}/5): {e}")
                retries += 1
                await asyncio.sleep(min(delay, 60))
                delay *= 2
        logger.error("Binance WebSocket: max retries exhausted")

    async def get_balance(self, asset: str) -> float:
        from binance import AsyncClient
        client = await AsyncClient.create(self._api_key, self._api_secret)
        try:
            account = await client.get_account()
            for b in account["balances"]:
                if b["asset"] == asset:
                    return float(b["free"])
            return 0.0
        finally:
            await client.close_connection()

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        from binance import AsyncClient
        from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_MARKET
        client = await AsyncClient.create(self._api_key, self._api_secret)
        symbol = self._to_symbol(pair)
        try:
            if side == "buy":
                order = await client.create_order(
                    symbol=symbol, side=SIDE_BUY,
                    type=ORDER_TYPE_MARKET, quoteOrderQty=amount_usdt,
                )
            else:
                # Sell: convert USDT to base quantity
                cached = self._price_cache.get(pair)
                bid = cached["bid"] if cached else 1.0
                base_qty = round(amount_usdt / bid, 6)
                order = await client.create_order(
                    symbol=symbol, side=SIDE_SELL,
                    type=ORDER_TYPE_MARKET, quantity=base_qty,
                )
            fills = order.get("fills", [])
            filled_qty   = sum(float(f["qty"])   for f in fills)
            filled_price = (sum(float(f["price"]) * float(f["qty"]) for f in fills)
                            / filled_qty) if filled_qty else 0.0
            return OrderResult(success=True, exchange=self.name, pair=pair,
                               side=side, filled_price=filled_price,
                               filled_amount=filled_qty)
        except Exception as e:
            return OrderResult(success=False, exchange=self.name, pair=pair,
                               side=side, filled_price=0.0, filled_amount=0.0,
                               error_msg=str(e))
        finally:
            await client.close_connection()

    async def close(self) -> None:
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
