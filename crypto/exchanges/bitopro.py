# crypto/exchanges/bitopro.py
"""
BitoPro (Taiwan) adapter.
REST API: https://github.com/bitoex/bitopro-offical-api-docs
WebSocket: wss://stream.bitopro.com:9443/ws/v1/pub/order-books/<pair>/<precision>
"""
import asyncio
import json
import logging
import os
import aiohttp
from crypto.exchanges.base import BaseExchange, OrderResult, DEFAULT_FEES, OrderbookCallback

logger = logging.getLogger(__name__)
REST_URL = "https://api.bitopro.com/v3"


class BitoproExchange(BaseExchange):
    name = "bitopro"

    def __init__(self, exchange_cfg: dict):
        self._fee = exchange_cfg.get("taker_fee_override") or DEFAULT_FEES["bitopro"]
        self._price_cache: dict[str, dict] = {}
        self._ws_tasks: list[asyncio.Task] = []
        self._api_key    = os.getenv("BITOPRO_API_KEY", "")
        self._api_secret = os.getenv("BITOPRO_API_SECRET", "")

    def _to_canonical(self, pair_str: str) -> str:
        """'BTC_TWD' or 'BTC_USDT' → 'BTC/TWD'"""
        return pair_str.replace("_", "/").upper()

    def _to_pair_path(self, pair: str) -> str:
        """'BTC/USDT' → 'BTC_USDT' (for URL path)"""
        return pair.replace("/", "_")

    async def get_tradable_pairs(self) -> list[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{REST_URL}/provisioning/currencies") as r:
                data = await r.json()
                pairs = []
                for item in data.get("data", []):
                    for pair in item.get("tradingPairs", []):
                        pairs.append(self._to_canonical(pair))
                return pairs

    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None:
        for pair in pairs:
            task = asyncio.create_task(self._ws_loop_pair(pair, callback))
            self._ws_tasks.append(task)

    async def _ws_loop_pair(self, pair: str, callback: OrderbookCallback) -> None:
        import websockets
        pair_path = self._to_pair_path(pair)
        url = f"wss://stream.bitopro.com:9443/ws/v1/pub/order-books/{pair_path}/5"
        retries, delay = 0, 1
        while retries < 5:
            try:
                async with websockets.connect(url) as ws:
                    retries, delay = 0, 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        asks = msg.get("asks", [])
                        bids = msg.get("bids", [])
                        if asks and bids:
                            ask = float(asks[0]["price"])
                            bid = float(bids[0]["price"])
                            self._price_cache[pair] = {"ask": ask, "bid": bid}
                            callback(self.name, pair, ask, bid)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"BitoPro WS error for {pair} (retry {retries+1}/5): {e}")
                retries += 1
                await asyncio.sleep(min(delay, 60))
                delay *= 2
        logger.error(f"BitoPro WebSocket {pair}: max retries exhausted")

    async def get_balance(self, asset: str) -> float:
        import hmac, hashlib, base64, time
        nonce = str(int(time.time() * 1000))
        payload = base64.b64encode(json.dumps({"identity": self._api_key,
                                               "nonce": nonce}).encode()).decode()
        sig = hmac.new(self._api_secret.encode(), payload.encode(),
                        hashlib.sha384).hexdigest()
        headers = {"X-BITOPRO-APIKEY": self._api_key,
                   "X-BITOPRO-PAYLOAD": payload,
                   "X-BITOPRO-SIGNATURE": sig}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{REST_URL}/accounts/balance", headers=headers) as r:
                data = await r.json()
                for acc in data.get("data", []):
                    if acc["currency"].upper() == asset.upper():
                        return float(acc["available"])
        return 0.0

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        import hmac, hashlib, base64, time
        pair_path = self._to_pair_path(pair).lower()
        try:
            if side == "buy":
                amount = amount_usdt
                action = "buy"
            else:
                cached = self._price_cache.get(pair)
                bid = cached["bid"] if cached else 1.0
                amount = round(amount_usdt / bid, 6)
                action = "sell"
            nonce = str(int(time.time() * 1000))
            body = {"action": action, "amount": str(amount), "type": "market"}
            payload = base64.b64encode(json.dumps({**body, "identity": self._api_key,
                                                    "nonce": nonce}).encode()).decode()
            sig = hmac.new(self._api_secret.encode(), payload.encode(),
                            hashlib.sha384).hexdigest()
            headers = {"X-BITOPRO-APIKEY": self._api_key,
                       "X-BITOPRO-PAYLOAD": payload,
                       "X-BITOPRO-SIGNATURE": sig,
                       "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{REST_URL}/orders/{pair_path}",
                                        json=body, headers=headers) as r:
                    data = await r.json()
                    filled = float(data.get("executedAmount", 0))
                    price  = float(data.get("avgExecutionPrice", 0))
                    return OrderResult(success=True, exchange=self.name, pair=pair,
                                       side=side, filled_price=price,
                                       filled_amount=filled)
        except Exception as e:
            return OrderResult(success=False, exchange=self.name, pair=pair,
                               side=side, filled_price=0.0, filled_amount=0.0,
                               error_msg=str(e))

    async def close(self) -> None:
        for task in self._ws_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._ws_tasks.clear()
