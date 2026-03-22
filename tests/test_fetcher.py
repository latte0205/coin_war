# tests/test_fetcher.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from data.fetcher import Fetcher

@pytest.fixture
def fetcher(tmp_path):
    return Fetcher(cache_dir=str(tmp_path), finmind_token="fake_token",
                   max_requests=600)

def make_ohlcv():
    idx = pd.date_range("2024-01-02", periods=5, freq="B")
    return pd.DataFrame({
        "Open": [100]*5, "High": [105]*5, "Low": [95]*5,
        "Close": [102]*5, "Volume": [1000]*5
    }, index=idx)

def test_get_price_returns_dataframe(fetcher):
    with patch("yfinance.download", return_value=make_ohlcv()):
        df = fetcher.get_price("2330", period="5d")
    assert not df.empty
    assert "Close" in df.columns

def test_get_price_skips_empty_yfinance_response(fetcher):
    with patch("yfinance.download", return_value=pd.DataFrame()):
        df = fetcher.get_price("9999", period="5d")
    assert df is None

def test_chips_layer_skipped_when_quota_insufficient(fetcher):
    fetcher._requests_used = 500
    result = fetcher.can_fetch_chips(watchlist_size=200)
    assert result is False

def test_chips_layer_allowed_when_quota_sufficient(fetcher):
    fetcher._requests_used = 0
    result = fetcher.can_fetch_chips(watchlist_size=200)
    assert result is True

def test_get_chips_returns_none_when_quota_exceeded(fetcher):
    fetcher._requests_used = 500
    result = fetcher.get_chips("2330", start="2024-01-01")
    assert result is None
