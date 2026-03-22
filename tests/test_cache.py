# tests/test_cache.py
import pandas as pd
import pytest
from pathlib import Path
from data.cache import Cache

@pytest.fixture
def tmp_cache(tmp_path):
    return Cache(cache_dir=str(tmp_path))

def test_cache_miss_returns_none(tmp_cache):
    assert tmp_cache.load("9999") is None

def test_cache_save_and_load_roundtrip(tmp_cache):
    df = pd.DataFrame({"Close": [100.0, 101.0]},
                      index=pd.date_range("2024-01-02", periods=2))
    tmp_cache.save("2330", df)
    loaded = tmp_cache.load("2330")
    pd.testing.assert_frame_equal(df, loaded)

def test_is_stale_when_last_date_before_latest_trading_day(tmp_cache):
    df = pd.DataFrame({"Close": [100.0]},
                      index=pd.DatetimeIndex(["2020-01-02"]))
    tmp_cache.save("2330", df)
    assert tmp_cache.is_stale("2330") is True

def test_is_not_stale_when_up_to_date(tmp_cache):
    import exchange_calendars as xcals
    cal = xcals.get_calendar("XTAI")
    latest = cal.schedule.index[cal.schedule.index <= pd.Timestamp.now()].max()
    df = pd.DataFrame({"Close": [100.0]},
                      index=pd.DatetimeIndex([latest]))
    tmp_cache.save("2330", df)
    assert tmp_cache.is_stale("2330") is False
