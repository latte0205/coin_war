# data/stock_list.py
"""Fetch the list of all TWSE + TPEx listed stocks from FinMind."""
import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


def get_all_stock_ids(finmind_token: str = "") -> list[str]:
    """
    Returns list of stock IDs for all TWSE + TPEx listed stocks.
    Falls back to a hardcoded starter list if FinMind is unavailable.
    """
    try:
        from finmind.data import DataLoader
        dl = DataLoader()
        if finmind_token:
            dl.login_by_token(api_token=finmind_token)

        df = dl.taiwan_stock_info()
        if df is None or df.empty:
            raise ValueError("Empty response from FinMind")

        # Filter to common stocks (type: 股票), exclude ETFs, warrants, etc.
        # stock_id format: 4-digit pure numeric = TWSE/TPEx common stock
        ids = df["stock_id"].dropna().astype(str).tolist()
        stock_ids = [s for s in ids if s.isdigit() and len(s) <= 5]
        logger.info(f"Fetched {len(stock_ids)} stocks from FinMind")
        return sorted(stock_ids)

    except Exception as e:
        logger.warning(f"Could not fetch stock list from FinMind: {e}. Using fallback list.")
        return _fallback_list()


def _fallback_list() -> list[str]:
    """Minimal fallback: major TWSE stocks by market cap."""
    return [
        "2330", "2317", "2454", "2382", "3711",
        "2308", "2881", "2882", "2886", "1301",
        "2412", "2002", "1303", "2303", "2379",
        "5876", "2891", "2884", "2880", "2892",
    ]
