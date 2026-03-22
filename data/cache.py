# data/cache.py
from pathlib import Path
import pandas as pd
import exchange_calendars as xcals


class Cache:
    def __init__(self, cache_dir: str = "cache/"):
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cal = xcals.get_calendar("XTAI")

    def _path(self, ticker: str) -> Path:
        return self._dir / f"{ticker}.parquet"

    def load(self, ticker: str) -> pd.DataFrame | None:
        p = self._path(ticker)
        if not p.exists():
            return None
        return pd.read_parquet(p)

    def save(self, ticker: str, df: pd.DataFrame) -> None:
        # Strip freq from index before saving so parquet roundtrip is lossless
        df = df.copy()
        df.index.freq = None
        df.to_parquet(self._path(ticker))

    def is_stale(self, ticker: str) -> bool:
        df = self.load(ticker)
        if df is None or df.empty:
            return True
        # cal.schedule.index is tz-naive; compare in tz-naive space
        now_naive = pd.Timestamp.now().normalize()
        latest_trading_day = (
            self._cal.schedule.index[
                self._cal.schedule.index <= now_naive
            ].max()
        )
        last_ts = pd.Timestamp(df.index[-1])
        # Strip tz if present so comparison is tz-naive vs tz-naive
        if last_ts.tzinfo is not None:
            last_cached = last_ts.tz_convert("UTC").tz_localize(None)
        else:
            last_cached = last_ts
        return last_cached < latest_trading_day
