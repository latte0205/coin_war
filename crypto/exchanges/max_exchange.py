# crypto/exchanges/max_exchange.py
"""
MAX Exchange (Taiwan) adapter.
Uses MAX REST API v3 + WebSocket v2.
"""
import asyncio
import json
import logging
import os
import aiohttp
from crypto.exchanges.base import BaseExchange, OrderResult, DEFAULT_FEES, OrderbookCallback

logger = logging.getLogger(__name__)
REST_URL = "https://max-api.maicoin.com"
WS_URL   = "wss://max-stream.maicoin.com/ws"


class MAXExchange(BaseExchange):
    name = "max"

    def __init__(self, exchange_cfg: dict):
        self._fee = exchange_cfg.get("taker_fee_override") or DEFAULT_FEES["max"]
        self._price_cache: dict[str, dict] = {}
        self._ws_task: asyncio.Task | None = None
        self._api_key    = os.getenv("MAX_API_KEY", "")
        self._api_secret = os.getenv("MAX_API_SECRET", "")

    def _to_canonical(self, market: str) -> str:
        """'btcusdt' or 'BTCUSDT' → 'BTC/USDT'"""
        m = market.upper()
        for q in ("USDT", "TWD", "BTC", "ETH"):
            if m.endswith(q):
                return f"{m[:-len(q)]}/{q}"
        return market.upper()

    def _to_market(self, pair: str) -> str:
        """'BTC/USDT' → 'btcusdt'"""
        return pair.replace("/", "").lower()

    async def get_tradable_pairs(self) -> list[str]:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{REST_URL}/api/v3/markets") as r:
                data = await r.json()
                return [self._to_canonical(m["id"])
                        for m in data if m.get("state") == "active"]

    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None:
        self._ws_task = asyncio.create_task(self._ws_loop(pairs, callback))

    async def _ws_loop(self, pairs: list[str], callback: OrderbookCallback) -> None:
        import websockets
        retries, delay = 0, 1
        subs = [{"channel": "book", "market": self._to_market(p), "depth": 1}
                for p in pairs]
        while retries < 5:
            try:
                async with websockets.connect(WS_URL) as ws:
                    await ws.send(json.dumps({"action": "sub", "subscriptions": subs}))
                    retries, delay = 0, 1
                    async for raw in ws:
                        msg = json.loads(raw)
                        if msg.get("e") != "book":
                            continue
                        asks = msg.get("a", [])
                        bids = msg.get("b", [])
                        if not asks or not bids:
                            continue
                        ask = float(asks[0][0])
                        bid = float(bids[0][0])
                        market = msg.get("M", "")
                        if market:
                            pair = self._to_canonical(market)
                            self._price_cache[pair] = {"ask": ask, "bid": bid}
                            callback(self.name, pair, ask, bid)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning(f"MAX WS error (retry {retries+1}/5): {e}")
                retries += 1
                await asyncio.sleep(min(delay, 60))
                delay *= 2
        logger.error("MAX WebSocket: max retries exhausted")

    async def get_balance(self, asset: str) -> float:
        import hmac, hashlib, time
        nonce = str(int(time.time() * 1000))
        path = "/api/v3/members/accounts"
        payload = f"GET|{path}|{nonce}"
        sig = hmac.new(self._api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        headers = {"X-MAX-ACCESSKEY": self._api_key,
                   "X-MAX-NONCE": nonce, "X-MAX-SIGNATURE": sig}
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{REST_URL}{path}", headers=headers) as r:
                data = await r.json()
                for acc in data:
                    if acc["currency"].upper() == asset.upper():
                        return float(acc["balance"])
        return 0.0

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult:
        import hmac, hashlib, time, urllib.parse
        market = self._to_market(pair)
        try:
            if side == "buy":
                payload_data = {"market": market, "side": "buy",
                                "volume": str(amount_usdt), "ord_type": "market"}
            else:
                cached = self._price_cache.get(pair)
                bid = cached["bid"] if cached else 1.0
                base_qty = str(round(amount_usdt / bid, 6))
                payload_data = {"market": market, "side": "sell",
                                "volume": base_qty, "ord_type": "market"}

            nonce = str(int(time.time() * 1000))
            qs = urllib.parse.urlencode(payload_data)
            path = "/api/v3/orders"
            sig_payload = f"POST|{path}|{nonce}|{qs}"
            sig = hmac.new(self._api_secret.encode(),
                            sig_payload.encode(), hashlib.sha256).hexdigest()
            headers = {"X-MAX-ACCESSKEY": self._api_key,
                       "X-MAX-NONCE": nonce, "X-MAX-SIGNATURE": sig}
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{REST_URL}{path}",
                                        data=payload_data, headers=headers) as r:
                    data = await r.json()
                    filled = float(data.get("executed_volume", 0))
                    price  = float(data.get("avg_price", 0))
                    return OrderResult(success=True, exchange=self.name, pair=pair,
                                       side=side, filled_price=price,
                                       filled_amount=filled)
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
