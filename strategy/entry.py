# strategy/entry.py
import pandas as pd
from signals.composite import CompositeScore, SignalStrength


class EntryFilter:
    def __init__(self, config: dict):
        self._cfg = config

    def should_enter(self, score: CompositeScore, price_df: pd.DataFrame) -> bool:
        if score.strength != SignalStrength.STRONG:
            return False

        close = price_df["Close"]
        if len(close) < 5:
            return False

        ma5 = close.rolling(5).mean().iloc[-1]
        if close.iloc[-1] <= ma5:
            return False

        vol_ratio = self._cfg["thresholds"]["volume_filter_ratio"]
        if "Volume" in price_df.columns and len(price_df) >= 20:
            vol_ma20 = price_df["Volume"].rolling(20).mean().iloc[-1]
            if price_df["Volume"].iloc[-1] < vol_ma20 * vol_ratio:
                return False

        return True
