# data/fetcher.py
import logging
import yfinance as yf
import pandas as pd
from data.cache import Cache

logger = logging.getLogger(__name__)


class Fetcher:
    def __init__(self, cache_dir: str = "cache/", finmind_token: str = "",
                 max_requests: int = 600):
        self._cache = Cache(cache_dir)
        self._token = finmind_token
        self._max_requests = max_requests
        self._requests_used = 0

    def get_price(self, ticker: str, period: str = "2y",
                  force_refresh: bool = False) -> pd.DataFrame | None:
        if not force_refresh and not self._cache.is_stale(ticker):
            return self._cache.load(ticker)

        tw_ticker = f"{ticker}.TW"
        df = yf.download(tw_ticker, period=period, progress=False, auto_adjust=True)
        if df is None or df.empty or "Close" not in df.columns:
            logger.warning(f"yfinance returned empty data for {ticker}")
            return None

        df.index = pd.to_datetime(df.index)
        self._cache.save(ticker, df)
        return df

    def can_fetch_chips(self, watchlist_size: int) -> bool:
        needed = watchlist_size * 2
        return (self._requests_used + needed) <= self._max_requests

    def get_chips(self, ticker: str, start: str) -> dict | None:
        """Returns dict with keys 'institutional' and 'margin', or None if quota exceeded."""
        if self._requests_used + 2 > self._max_requests:
            return None
        try:
            from finmind.data import DataLoader
            dl = DataLoader()
            dl.login_by_token(api_token=self._token)

            inst = dl.taiwan_stock_institutional_investors(
                stock_id=ticker, start_date=start
            )
            self._requests_used += 1

            margin = dl.taiwan_stock_margin_purchase_short_sale(
                stock_id=ticker, start_date=start
            )
            self._requests_used += 1

            return {"institutional": inst, "margin": margin}
        except Exception as e:
            logger.warning(f"FinMind error for {ticker}: {e}")
            return None
