# crypto/exchanges/okx.py
import asyncio
import logging
import os
from crypto.exchanges.base import BaseExchange, OrderResult, DEFAULT_FEES, OrderbookCallback

logger = logging.getLogger(__name__)


class OKXExchange(BaseExchange):
    name = "okx"

    def __init__(self, exchange_cfg: dict):
        self._fee = exchange_cfg.get("taker_fee_override") or DEFAULT_FEES["okx"]
        self._price_cache: dict[str, dict] = {}
        self._ws_task: asyncio.Task | None = None
        self._api_key    = os.getenv("OKX_API_KEY", "")
        self._api_secret = os.getenv("OKX_API_SECRET", "")
        self._passphrase = os.getenv("OKX_PASSPHRASE", "")

    def _to_canonical(self, symbol: str) -> str:
        """'BTC-USDT' → 'BTC/USDT'"""
        return symbol.replace("-", "/").upper()

    def _to_symbol(self, pair: str) -> str:
        """'BTC/USDT' → 'BTC-USDT'"""
        return pair.replace("/", "-")

    async def get_tradable_pairs(self) -> list[str]:
        from okx.MarketData import MarketAPI
        api = MarketAPI(flag="0")  # 0=live
        result = api.get_tickers(instType="SPOT")
        return [self._to_canonical(t["instId"])
                for t in result.get("data", [])
                if t["instId"].endswith("-USDT")]

    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None:
        self._ws_task = asyncio.create_task(self._ws_loop(pairs, callback))

    async def _ws_loop(self, pairs: list[str], callback: OrderbookCallback) -> None:
        import websockets, json
        retries, delay = 0, 1
        symbols = [self._to_symbol(p) for p in pairs]
        url = "wss://ws.okx.com:8443/ws/v5/public"
        args = [{"channel": "bbo-tbt", "instId": s} for s in symbols]
        while retries < 5:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps({"op": "subscribe", "args": args}))
                    retries, delay = 0, 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        data = msg.get("data", [{}])[0] if msg.get("data") else {}
                        if not data:
                            continue
                        ask = float(data["asks"][0][0]) if data.get("asks") else 0
                        bid = float(data["bids"][0][0]) if data.get("bids") else 0
                        inst = msg.get("arg", {}).get("instId", "")
                        if inst and ask and bid:
                            pair = self._to_canonical(inst)
                            self._price_cache[pair] = {"ask": ask, "bid": bid}
                            callback(self.name, pair, ask, bid)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"OKX WS error (retry {retries+1}/5): {e}")
                retries += 1
                await asyncio.sleep(min(delay, 60))
                delay *= 2
        logger.error("OKX WebSocket: max retries exhausted")

    async def get_balance(self, asset: str) -> float:
        from okx.Account import AccountAPI
        api = AccountAPI(self._api_key, self._api_secret, self._passphrase, flag="0")
        result = api.get_account_balance()
        for detail in result.get("data", [{}])[0].get("details", []):
            if detail["ccy"] == asset:
                return float(detail["availBal"])
        return 0.0

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        from okx.Trade import TradeAPI
        api = TradeAPI(self._api_key, self._api_secret, self._passphrase, flag="0")
        inst_id = self._to_symbol(pair)
        try:
            if side == "buy":
                r = api.place_order(instId=inst_id, tdMode="cash", side="buy",
                                    ordType="market", sz=str(amount_usdt),
                                    tgtCcy="quote_ccy")
            else:
                cached = self._price_cache.get(pair)
                bid = cached["bid"] if cached else 1.0
                base_qty = str(round(amount_usdt / bid, 6))
                r = api.place_order(instId=inst_id, tdMode="cash", side="sell",
                                    ordType="market", sz=base_qty)
            data = r.get("data", [{}])[0]
            filled = float(data.get("fillSz", 0))
            price  = float(data.get("avgPx", 0))
            return OrderResult(success=True, exchange=self.name, pair=pair,
                               side=side, filled_price=price, filled_amount=filled)
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
