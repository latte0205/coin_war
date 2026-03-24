# crypto/exchanges/bybit.py
import asyncio
import logging
import os
from crypto.exchanges.base import BaseExchange, OrderResult, DEFAULT_FEES, OrderbookCallback

logger = logging.getLogger(__name__)

_KNOWN_QUOTES = ("USDT", "BTC", "ETH")


class BybitExchange(BaseExchange):
    name = "bybit"

    def __init__(self, exchange_cfg: dict):
        self._fee = exchange_cfg.get("taker_fee_override") or DEFAULT_FEES["bybit"]
        self._price_cache: dict[str, dict] = {}
        self._ws_task: asyncio.Task | None = None
        self._api_key    = os.getenv("BYBIT_API_KEY", "")
        self._api_secret = os.getenv("BYBIT_API_SECRET", "")

    def _to_canonical(self, symbol: str) -> str:
        """'BTCUSDT' → 'BTC/USDT'"""
        symbol = symbol.upper()
        for q in _KNOWN_QUOTES:
            if symbol.endswith(q):
                return f"{symbol[:-len(q)]}/{q}"
        mid = len(symbol) // 2
        return f"{symbol[:mid]}/{symbol[mid:]}"

    def _to_symbol(self, pair: str) -> str:
        return pair.replace("/", "")

    async def get_tradable_pairs(self) -> list[str]:
        from pybit.unified_trading import HTTP
        session = HTTP()
        result = session.get_instruments_info(category="spot")
        return [self._to_canonical(s["symbol"])
                for s in result["result"]["list"]
                if s["symbol"].endswith("USDT")]

    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None:
        self._ws_task = asyncio.create_task(self._ws_loop(pairs, callback))

    async def _ws_loop(self, pairs: list[str], callback: OrderbookCallback) -> None:
        import websockets, json
        retries, delay = 0, 1
        topics = [f"orderbook.1.{self._to_symbol(p)}" for p in pairs]
        url = "wss://stream.bybit.com/v5/public/spot"
        while retries < 5:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps({"op": "subscribe", "args": topics}))
                    retries, delay = 0, 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        data = msg.get("data", {})
                        if not data:
                            continue
                        ask = float(data["a"][0][0]) if data.get("a") else 0
                        bid = float(data["b"][0][0]) if data.get("b") else 0
                        sym = msg.get("topic", "").split(".")[-1]
                        if sym and ask and bid:
                            pair = self._to_canonical(sym)
                            self._price_cache[pair] = {"ask": ask, "bid": bid}
                            callback(self.name, pair, ask, bid)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"Bybit WS error (retry {retries+1}/5): {e}")
                retries += 1
                await asyncio.sleep(min(delay, 60))
                delay *= 2
        logger.error("Bybit WebSocket: max retries exhausted")

    async def get_balance(self, asset: str) -> float:
        from pybit.unified_trading import HTTP
        session = HTTP(api_key=self._api_key, api_secret=self._api_secret)
        result = session.get_wallet_balance(accountType="SPOT")
        for coin in result["result"]["list"][0].get("coin", []):
            if coin["coin"] == asset:
                return float(coin["availableToWithdraw"])
        return 0.0

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        from pybit.unified_trading import HTTP
        session = HTTP(api_key=self._api_key, api_secret=self._api_secret)
        symbol = self._to_symbol(pair)
        try:
            if side == "buy":
                r = session.place_order(category="spot", symbol=symbol,
                                        side="Buy", orderType="MARKET",
                                        marketUnit="quoteCoin", qty=str(amount_usdt))
            else:
                cached = self._price_cache.get(pair)
                bid = cached["bid"] if cached else 1.0
                base_qty = str(round(amount_usdt / bid, 6))
                r = session.place_order(category="spot", symbol=symbol,
                                        side="Sell", orderType="MARKET", qty=base_qty)
            info = r["result"]
            return OrderResult(success=True, exchange=self.name, pair=pair,
                               side=side,
                               filled_price=float(info.get("avgPrice", 0)),
                               filled_amount=float(info.get("cumExecQty", 0)))
        except Exception as e:
            return OrderResult(success=False, exchange=self.name, pair=pair,
                               side=side, filled_price=0.0, filled_amount=0.0,
                               error_msg=str(e))

    async def close(self) -> None:
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
