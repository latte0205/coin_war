# Taiwan Stock Signal Analysis System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立台股全自動訊號分析、回測與下單輔助系統，整合技術指標、量能、籌碼三類訊號，提供每日掃描、回測報告與紙上交易功能。

**Architecture:** 五層管線架構 — 資料抓取（yfinance + FinMind）→ 訊號計算（技術/量能/籌碼）→ 複合評分 → 策略過濾（進出場規則）→ 回測 / 紙上交易 / CLI 輸出。資料以 parquet 本地快取；籌碼資料採「全量或全略」降級策略避免排名偏差。

**Tech Stack:** Python 3.11+, yfinance, ta, PyFinmind, exchange_calendars, pandas, numpy, rich, pyyaml, python-dotenv, pytest

> **Note on backtesting.py:** The spec mentions `backtesting.py` as the framework. After evaluation, a custom simulation loop is used instead — `backtesting.py`'s `Strategy.next()` API is incompatible with our multi-signal composite scoring approach (which requires a full DataFrame window per bar). The custom engine replicates all required metrics (total return, max drawdown, Sharpe, win rate) with correct Taiwan transaction costs.

**Spec:** `docs/superpowers/specs/2026-03-22-taiwan-stock-signal-design.md`

---

## File Map

| 檔案 | 責任 |
|---|---|
| `requirements.txt` | 所有依賴套件 |
| `.gitignore` | 排除 .env、cache/、__pycache__ |
| `.env.example` | API key 範本 |
| `config/settings.yaml` | 觀察清單、閾值、倉位、出場參數 |
| `data/cache.py` | parquet 快取讀寫 + 過期檢查（用 XTAI 日曆） |
| `data/fetcher.py` | yfinance 價格抓取 + FinMind 籌碼抓取 + 配額管理 |
| `signals/technical.py` | KD / MACD / RSI / 布林通道 / 均線多頭排列 → 分數 |
| `signals/volume.py` | 爆量突破 / 縮量放量 / OBV → 分數 |
| `signals/chips.py` | 外資連買 / 投信連買 / 法人合力 / 融資減少 → 分數 |
| `signals/composite.py` | 三類分數加總 → 最終評分 + 強弱分類 |
| `strategy/entry.py` | 進場過濾（評分 ≥ 14、量能、MA5）→ bool |
| `strategy/exit.py` | 停損 / 停利 / 訊號停損 / 時間停損 → 出場訊號 |
| `orders/base.py` | ABC OrderBase + OrderResult + Position dataclass |
| `orders/paper.py` | 繼承 OrderBase；記憶體持倉 + 手續費模擬 |
| `orders/broker.py` | 繼承 OrderBase；預留真實券商 API stub |
| `backtest/engine.py` | 自製回測引擎（含台灣手續費 + 滑點 + equity curve）|
| `backtest/report.py` | 回測結果 → HTML + CSV 報告 |
| `main.py` | CLI：scan / backtest / paper / positions 指令 |
| `tests/` | 每個模組的單元測試 |

---

## Task 1: 專案骨架與依賴

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `config/settings.yaml`
- Create: `data/__init__.py`, `signals/__init__.py`, `strategy/__init__.py`, `orders/__init__.py`, `backtest/__init__.py`

- [ ] **Step 1: 建立 requirements.txt**

```
yfinance>=0.2.50
pandas>=2.0
numpy>=1.26
ta>=0.11
PyFinmind>=0.12
backtesting>=0.3.3
exchange-calendars>=4.5
rich>=13.0
pyyaml>=6.0
python-dotenv>=1.0
pytest>=8.0
pytest-mock>=3.12
```

- [ ] **Step 2: 建立 .gitignore**

```
.env
cache/
__pycache__/
*.pyc
*.parquet
reports/*.html
reports/*.csv
.pytest_cache/
```

- [ ] **Step 3: 建立 .env.example**

```
# FinMind API token（免費帳號於 https://finmindtrade.com/ 申請）
FINMIND_TOKEN=your_token_here

# 券商 API（預留，實際下單時填入）
BROKER_API_KEY=
BROKER_API_SECRET=
```

- [ ] **Step 4: 建立 config/settings.yaml**

```yaml
watchlist:
  - "2330"  # 台積電
  - "2317"  # 鴻海
  - "2454"  # 聯發科
  - "2382"  # 廣達
  - "3711"  # 日月光投控
  - "2308"  # 台達電
  - "2881"  # 富邦金
  - "2882"  # 國泰金
  - "2886"  # 兆豐金
  - "1301"  # 台塑

thresholds:
  strong_signal: 14
  watch_signal: 10
  exit_signal: 6
  volume_filter_ratio: 0.8

position:
  size_pct: 0.10
  max_positions: 8
  max_exposure_pct: 0.80

exit:
  stop_loss_pct: -0.07
  take_profit_1_pct: 0.15
  take_profit_1_qty_pct: 0.50
  take_profit_2_pct: 0.20
  time_stop_days: 20

data:
  cache_dir: "cache/"
  max_api_requests_per_day: 600
  warmup_days: 90
```

- [ ] **Step 5: 建立所有 `__init__.py` 空檔**

```bash
touch data/__init__.py signals/__init__.py strategy/__init__.py orders/__init__.py backtest/__init__.py tests/__init__.py
```

- [ ] **Step 6: 安裝依賴**

```bash
pip install -r requirements.txt
```

Expected: 所有套件安裝成功，無 error

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore .env.example config/settings.yaml data/__init__.py signals/__init__.py strategy/__init__.py orders/__init__.py backtest/__init__.py tests/__init__.py
git commit -m "feat: project scaffold, dependencies, config"
```

---

## Task 2: 快取層 (data/cache.py)

**Files:**
- Create: `data/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: 寫測試**

```python
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
    # 建立一個最後日期為過去的 parquet
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
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_cache.py -v
```

Expected: `ModuleNotFoundError: No module named 'data.cache'`

- [ ] **Step 3: 實作 data/cache.py**

```python
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
        df.to_parquet(self._path(ticker))

    def is_stale(self, ticker: str) -> bool:
        df = self.load(ticker)
        if df is None or df.empty:
            return True
        latest_trading_day = (
            self._cal.schedule.index[
                self._cal.schedule.index <= pd.Timestamp.now(tz="UTC").normalize()
            ].max()
        )
        last_ts = pd.Timestamp(df.index[-1])
        last_cached = last_ts.tz_localize("UTC") if last_ts.tzinfo is None else last_ts
        return last_cached < latest_trading_day
```

- [ ] **Step 4: 執行測試確認 PASS**

```bash
pytest tests/test_cache.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add data/cache.py tests/test_cache.py
git commit -m "feat: add cache layer with XTAI calendar staleness check"
```

---

## Task 3: 資料抓取層 (data/fetcher.py)

**Files:**
- Create: `data/fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: 寫測試（使用 mock）**

```python
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
    # 400 requests needed (200 tickers × 2 datasets), only 100 available
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
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_fetcher.py -v
```

Expected: `ModuleNotFoundError: No module named 'data.fetcher'`

- [ ] **Step 3: 實作 data/fetcher.py**

```python
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
```

- [ ] **Step 4: 執行測試確認 PASS**

```bash
pytest tests/test_fetcher.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add data/fetcher.py tests/test_fetcher.py
git commit -m "feat: data fetcher with yfinance price and FinMind chips quota guard"
```

---

## Task 4: 技術指標訊號 (signals/technical.py)

**Files:**
- Create: `signals/technical.py`
- Create: `tests/test_technical.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_technical.py
import pandas as pd
import numpy as np
import pytest
from signals.technical import TechnicalSignals

def make_df(closes, volumes=None):
    n = len(closes)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    highs = [c * 1.02 for c in closes]
    lows = [c * 0.98 for c in closes]
    vols = volumes or [100_000] * n
    return pd.DataFrame({
        "Open": closes, "High": highs, "Low": lows,
        "Close": closes, "Volume": vols
    }, index=idx)

def test_ma_bull_arrangement_true():
    # 60日上升趨勢確保 5>10>20>60MA
    closes = list(range(50, 160))  # 110根遞增
    df = make_df(closes)
    sig = TechnicalSignals(df)
    score, flags = sig.score()
    assert flags["ma_bull"]

def test_ma_bull_arrangement_false():
    closes = list(range(150, 40, -1))  # 遞減
    df = make_df(closes)
    sig = TechnicalSignals(df)
    score, flags = sig.score()
    assert not flags["ma_bull"]

def test_score_returns_int_between_0_and_9():
    closes = list(range(100, 210))
    df = make_df(closes)
    sig = TechnicalSignals(df)
    score, _ = sig.score()
    assert 0 <= score <= 9

def test_rsi_oversold_bounce():
    # 製造確定會觸發 RSI 超賣反彈的序列：先急跌壓低 RSI < 30，再連續上漲
    # 前 20 根穩定，接著急跌 10 根把 RSI 壓到 < 30，再連漲把 RSI 拉回 > 35
    closes = [100.0] * 20
    for _ in range(12):   # 急跌 → RSI 進超賣
        closes.append(closes[-1] * 0.97)
    for _ in range(10):   # 連漲 → RSI 回升
        closes.append(closes[-1] * 1.03)
    df = make_df(closes)
    sig = TechnicalSignals(df)
    _, flags = sig.score()
    assert flags["rsi_bounce"] is True
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_technical.py -v
```

- [ ] **Step 3: 實作 signals/technical.py**

```python
# signals/technical.py
import pandas as pd
import ta


class TechnicalSignals:
    def __init__(self, df: pd.DataFrame):
        self._df = df.copy()

    def score(self) -> tuple[int, dict]:
        df = self._df
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        flags = {}
        total = 0

        # KD 黃金交叉 (+2)
        stoch = ta.momentum.StochasticOscillator(high, low, close, window=9, smooth_window=3)
        k = stoch.stoch()
        d = stoch.stoch_signal()
        kd_cross = (k.shift(1) < d.shift(1)) & (k > d)
        flags["kd_cross"] = bool(kd_cross.iloc[-1])
        if flags["kd_cross"]:
            total += 2

        # MACD 黃金交叉 (+2)
        macd_ind = ta.trend.MACD(close)
        macd_line = macd_ind.macd()
        signal_line = macd_ind.macd_signal()
        macd_cross = (macd_line.shift(1) < signal_line.shift(1)) & (macd_line > signal_line)
        flags["macd_cross"] = bool(macd_cross.iloc[-1])
        if flags["macd_cross"]:
            total += 2

        # RSI 超賣反彈 (+2)
        rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
        rsi_bounce = (rsi.shift(1) < 30) & (rsi > 35)
        flags["rsi_bounce"] = bool(rsi_bounce.iloc[-1])
        if flags["rsi_bounce"]:
            total += 2

        # 布林通道突破 (+1)
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_break = close > bb.bollinger_hband()
        flags["bb_break"] = bool(bb_break.iloc[-1])
        if flags["bb_break"]:
            total += 1

        # 均線多頭排列 (+2)
        if len(close) >= 60:
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]
            flags["ma_bull"] = bool(ma5 > ma10 > ma20 > ma60)
        else:
            flags["ma_bull"] = False
        if flags["ma_bull"]:
            total += 2

        return total, flags
```

- [ ] **Step 4: 執行測試確認 PASS**

```bash
pytest tests/test_technical.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add signals/technical.py tests/test_technical.py
git commit -m "feat: technical signals (KD/MACD/RSI/BB/MA) with scoring"
```

---

## Task 5: 量能訊號 (signals/volume.py)

**Files:**
- Create: `signals/volume.py`
- Create: `tests/test_volume.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_volume.py
import pandas as pd
import pytest
from signals.volume import VolumeSignals

def make_df(closes, volumes):
    n = len(closes)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": closes, "High": [c*1.01 for c in closes],
        "Low": [c*0.99 for c in closes],
        "Close": closes, "Volume": volumes
    }, index=idx)

def test_volume_breakout_detected():
    # 前 20 日均量 100, 最後一日量 250 (>2x) 且收陽
    closes = [100] * 20 + [101]  # 最後一根收陽
    volumes = [100_000] * 20 + [250_000]
    df = make_df(closes, volumes)
    sig = VolumeSignals(df)
    score, flags = sig.score()
    assert flags["vol_breakout"]
    assert score >= 3

def test_volume_breakout_not_detected_when_bearish():
    closes = [100] * 20 + [99]  # 收陰
    volumes = [100_000] * 20 + [250_000]
    df = make_df(closes, volumes)
    sig = VolumeSignals(df)
    _, flags = sig.score()
    assert not flags["vol_breakout"]

def test_score_max_6():
    closes = list(range(90, 121))
    volumes = [100_000] * 25 + [350_000]
    df = make_df(closes, volumes)
    sig = VolumeSignals(df)
    score, _ = sig.score()
    assert 0 <= score <= 6
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_volume.py -v
```

- [ ] **Step 3: 實作 signals/volume.py**

```python
# signals/volume.py
import pandas as pd
import ta


class VolumeSignals:
    def __init__(self, df: pd.DataFrame):
        self._df = df.copy()

    def score(self) -> tuple[int, dict]:
        df = self._df
        close = df["Close"]
        volume = df["Volume"]
        flags = {}
        total = 0

        vol_ma20 = volume.rolling(20).mean()

        # 爆量突破 (+3): 量 > 20日均量×2 且收陽
        vol_surge = volume.iloc[-1] > vol_ma20.iloc[-1] * 2
        is_bullish = close.iloc[-1] > df["Open"].iloc[-1]
        flags["vol_breakout"] = bool(vol_surge and is_bullish)
        if flags["vol_breakout"]:
            total += 3

        # 縮量整理後放量 (+2): 前5日量均低於20日均量，今日量 > 1.5x 20日均量
        if len(df) >= 26:
            prev5_avg = volume.iloc[-6:-1].mean()
            contracted = prev5_avg < vol_ma20.iloc[-1]
            expanded = volume.iloc[-1] > vol_ma20.iloc[-1] * 1.5
            flags["vol_expand_after_contract"] = bool(contracted and expanded)
        else:
            flags["vol_expand_after_contract"] = False
        if flags["vol_expand_after_contract"]:
            total += 2

        # OBV 創近10日新高 (+1)
        obv = ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume()
        if len(obv.dropna()) >= 11:
            obv_new_high = obv.iloc[-1] == obv.iloc[-11:].max()
            flags["obv_high"] = bool(obv_new_high)
        else:
            flags["obv_high"] = False
        if flags["obv_high"]:
            total += 1

        return total, flags
```

- [ ] **Step 4: 執行測試確認 PASS**

```bash
pytest tests/test_volume.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add signals/volume.py tests/test_volume.py
git commit -m "feat: volume signals (breakout/contraction-expansion/OBV) with scoring"
```

---

## Task 6: 籌碼訊號 (signals/chips.py)

**Files:**
- Create: `signals/chips.py`
- Create: `tests/test_chips.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_chips.py
import pandas as pd
import pytest
from signals.chips import ChipsSignals

def make_inst(foreign_values, trust_values):
    """三大法人 DataFrame，columns: date, name, buy, sell, diff"""
    rows = []
    dates = pd.date_range("2024-01-02", periods=max(len(foreign_values), len(trust_values)), freq="B")
    for i, v in enumerate(foreign_values):
        rows.append({"date": dates[i], "name": "Foreign_Investor", "buy": max(v,0)*1e6, "sell": max(-v,0)*1e6, "diff": v*1e6})
    for i, v in enumerate(trust_values):
        rows.append({"date": dates[i], "name": "Investment_Trust", "buy": max(v,0)*1e6, "sell": max(-v,0)*1e6, "diff": v*1e6})
    return pd.DataFrame(rows)

def make_margin(margin_balance_changes):
    """融資融券 DataFrame"""
    dates = pd.date_range("2024-01-02", periods=len(margin_balance_changes), freq="B")
    rows = [{"date": d, "MarginPurchaseBalance": 10000 + sum(margin_balance_changes[:i+1])}
            for i, d in enumerate(dates)]
    return pd.DataFrame(rows)

def test_foreign_consecutive_buy_3days():
    inst = make_inst([100, 200, 300], [50, 60])
    sig = ChipsSignals(inst_df=inst, margin_df=make_margin([0,0,0]), price_df=pd.DataFrame())
    _, flags = sig.score()
    assert flags["foreign_consecutive"]

def test_no_foreign_consecutive_when_gap():
    inst = make_inst([100, -50, 300], [])
    sig = ChipsSignals(inst_df=inst, margin_df=make_margin([0,0,0]), price_df=pd.DataFrame())
    _, flags = sig.score()
    assert not flags["foreign_consecutive"]

def test_score_max_10():
    inst = make_inst([100]*5, [50]*5)
    sig = ChipsSignals(inst_df=inst, margin_df=make_margin([-200, -200, -200]), price_df=pd.DataFrame({"Close": [100,101,102]}))
    score, _ = sig.score()
    assert 0 <= score <= 10
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_chips.py -v
```

- [ ] **Step 3: 實作 signals/chips.py**

```python
# signals/chips.py
import pandas as pd


class ChipsSignals:
    def __init__(self, inst_df: pd.DataFrame, margin_df: pd.DataFrame,
                 price_df: pd.DataFrame):
        self._inst = inst_df
        self._margin = margin_df
        self._price = price_df

    def score(self) -> tuple[int, dict]:
        flags = {}
        total = 0

        foreign = self._inst[self._inst["name"] == "Foreign_Investor"].sort_values("date")
        trust = self._inst[self._inst["name"] == "Investment_Trust"].sort_values("date")

        # 外資連買 3 日以上 (+3)
        if len(foreign) >= 3:
            last3 = foreign["diff"].iloc[-3:]
            flags["foreign_consecutive"] = bool((last3 > 0).all())
        else:
            flags["foreign_consecutive"] = False
        if flags["foreign_consecutive"]:
            total += 3

        # 投信連買 2 日以上 (+2)
        if len(trust) >= 2:
            last2 = trust["diff"].iloc[-2:]
            flags["trust_consecutive"] = bool((last2 > 0).all())
        else:
            flags["trust_consecutive"] = False
        if flags["trust_consecutive"]:
            total += 2

        # 法人合力買超（外資 + 投信同日雙買超）(+3)
        if not foreign.empty and not trust.empty:
            last_date = max(foreign["date"].iloc[-1], trust["date"].iloc[-1])
            f_today = foreign[foreign["date"] == last_date]["diff"].sum()
            t_today = trust[trust["date"] == last_date]["diff"].sum()
            flags["joint_buy"] = bool(f_today > 0 and t_today > 0)
        else:
            flags["joint_buy"] = False
        if flags["joint_buy"]:
            total += 3

        # 融資減少 + 股價上漲 (+2)
        if len(self._margin) >= 2 and len(self._price) >= 2:
            mb = self._margin["MarginPurchaseBalance"]
            margin_dec = (mb.iloc[-2] - mb.iloc[-1]) / mb.iloc[-2] > 0.01 if mb.iloc[-2] != 0 else False
            price_up = self._price["Close"].iloc[-1] > self._price["Close"].iloc[-2]
            flags["margin_reduce_price_up"] = bool(margin_dec and price_up)
        else:
            flags["margin_reduce_price_up"] = False
        if flags["margin_reduce_price_up"]:
            total += 2

        return total, flags
```

- [ ] **Step 4: 執行測試確認 PASS**

```bash
pytest tests/test_chips.py -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add signals/chips.py tests/test_chips.py
git commit -m "feat: chips signals (foreign/trust/joint buy, margin) with scoring"
```

---

## Task 7: 複合評分 (signals/composite.py)

**Files:**
- Create: `signals/composite.py`
- Create: `tests/test_composite.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_composite.py
from signals.composite import CompositeScore, SignalStrength

def test_strong_signal_when_score_ge_14():
    cs = CompositeScore(tech_score=6, vol_score=5, chips_score=4)
    assert cs.total == 15
    assert cs.strength == SignalStrength.STRONG

def test_watch_when_score_10_to_13():
    cs = CompositeScore(tech_score=4, vol_score=4, chips_score=4)
    assert cs.total == 12
    assert cs.strength == SignalStrength.WATCH

def test_weak_when_score_below_10():
    cs = CompositeScore(tech_score=1, vol_score=2, chips_score=3)
    assert cs.total == 6
    assert cs.strength == SignalStrength.WEAK

def test_max_score_is_25():
    cs = CompositeScore(tech_score=9, vol_score=6, chips_score=10)
    assert cs.total == 25

def test_chips_score_ignored_when_unavailable():
    cs = CompositeScore(tech_score=8, vol_score=5, chips_score=None)
    assert cs.total == 13
    assert cs.chips_available is False
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_composite.py -v
```

- [ ] **Step 3: 實作 signals/composite.py**

```python
# signals/composite.py
from dataclasses import dataclass
from enum import Enum


class SignalStrength(Enum):
    STRONG = "strong"   # ≥ 14
    WATCH = "watch"     # 10–13
    WEAK = "weak"       # < 10


@dataclass
class CompositeScore:
    tech_score: int
    vol_score: int
    chips_score: int | None  # None = chips data unavailable

    @property
    def chips_available(self) -> bool:
        return self.chips_score is not None

    @property
    def total(self) -> int:
        return self.tech_score + self.vol_score + (self.chips_score or 0)

    @property
    def strength(self) -> SignalStrength:
        if self.total >= 14:
            return SignalStrength.STRONG
        elif self.total >= 10:
            return SignalStrength.WATCH
        return SignalStrength.WEAK
```

- [ ] **Step 4: 執行測試確認 PASS**

```bash
pytest tests/test_composite.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add signals/composite.py tests/test_composite.py
git commit -m "feat: composite score with 25-point max and signal strength enum"
```

---

## Task 8: 進出場策略 (strategy/entry.py + exit.py)

**Files:**
- Create: `strategy/entry.py`
- Create: `strategy/exit.py`
- Create: `tests/test_strategy.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_strategy.py
import pandas as pd
import pytest
from signals.composite import CompositeScore
from strategy.entry import EntryFilter
from strategy.exit import ExitSignal

def make_price_df(closes):
    idx = pd.date_range("2023-01-02", periods=len(closes), freq="B")
    vols = [100_000] * len(closes)
    vol_ma = 80_000
    return pd.DataFrame({"Close": closes, "Volume": vols,
                          "vol_ma20": [vol_ma]*len(closes)}, index=idx)

# --- Entry ---
def test_entry_allowed_when_all_conditions_met():
    cs = CompositeScore(tech_score=6, vol_score=5, chips_score=4)  # 15 ≥ 14
    closes = list(range(90, 106))  # 上升趨勢，last > ma5
    df = make_price_df(closes)
    ef = EntryFilter(config={"thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8}})
    assert ef.should_enter(cs, df) is True

def test_entry_blocked_when_score_too_low():
    cs = CompositeScore(tech_score=3, vol_score=2, chips_score=2)  # 7 < 14
    df = make_price_df(list(range(90, 106)))
    ef = EntryFilter(config={"thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8}})
    assert ef.should_enter(cs, df) is False

def test_entry_blocked_when_price_below_ma5():
    cs = CompositeScore(tech_score=6, vol_score=5, chips_score=4)
    closes = list(range(106, 90, -1))  # 下降趨勢
    df = make_price_df(closes)
    ef = EntryFilter(config={"thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8}})
    assert ef.should_enter(cs, df) is False

# --- Exit ---
def test_stop_loss_triggered():
    es = ExitSignal(entry_price=100.0, config={
        "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
                 "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
                 "time_stop_days": 20}})
    action = es.check(current_price=92.0, days_held=3, current_score=12)
    assert action["exit"] is True
    assert action["reason"] == "stop_loss"
    assert action["qty_pct"] == 1.0

def test_partial_take_profit_at_15pct():
    es = ExitSignal(entry_price=100.0, config={
        "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
                 "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
                 "time_stop_days": 20}})
    action = es.check(current_price=116.0, days_held=5, current_score=15)
    assert action["exit"] is True
    assert action["reason"] == "take_profit_1"
    assert action["qty_pct"] == 0.5

def test_no_exit_when_conditions_not_met():
    es = ExitSignal(entry_price=100.0, config={
        "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
                 "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
                 "time_stop_days": 20}})
    action = es.check(current_price=105.0, days_held=5, current_score=14)
    assert action["exit"] is False
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_strategy.py -v
```

- [ ] **Step 3: 實作 strategy/entry.py**

```python
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
```

- [ ] **Step 4: 實作 strategy/exit.py**

```python
# strategy/exit.py


class ExitSignal:
    def __init__(self, entry_price: float, config: dict):
        self._entry = entry_price
        self._cfg = config["exit"]
        self._tp1_triggered = False

    def check(self, current_price: float, days_held: int,
              current_score: int) -> dict:
        pnl = (current_price - self._entry) / self._entry

        # 停損
        if pnl <= self._cfg["stop_loss_pct"]:
            return {"exit": True, "reason": "stop_loss", "qty_pct": 1.0}

        # 訊號停損
        if current_score < 6:
            return {"exit": True, "reason": "signal_stop", "qty_pct": 1.0}

        # 時間停損
        if days_held >= self._cfg["time_stop_days"] and pnl < 0.05:
            return {"exit": True, "reason": "time_stop", "qty_pct": 1.0}

        # 分批停利 1
        if not self._tp1_triggered and pnl >= self._cfg["take_profit_1_pct"]:
            self._tp1_triggered = True
            return {"exit": True, "reason": "take_profit_1",
                    "qty_pct": self._cfg["take_profit_1_qty_pct"]}

        # 分批停利 2
        if self._tp1_triggered and pnl >= self._cfg["take_profit_2_pct"]:
            return {"exit": True, "reason": "take_profit_2", "qty_pct": 1.0}

        return {"exit": False, "reason": None, "qty_pct": 0.0}
```

- [ ] **Step 5: 執行測試確認 PASS**

```bash
pytest tests/test_strategy.py -v
```

Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add strategy/entry.py strategy/exit.py tests/test_strategy.py
git commit -m "feat: entry/exit strategy with stop-loss, partial take-profit, signal/time stops"
```

---

## Task 9: 下單介面 (orders/base.py + paper.py + broker.py)

**Files:**
- Create: `orders/base.py`
- Create: `orders/paper.py`
- Create: `orders/broker.py`
- Create: `tests/test_paper.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_paper.py
import pytest
from orders.paper import PaperBroker

@pytest.fixture
def broker():
    return PaperBroker(initial_capital=1_000_000)

def test_buy_reduces_balance(broker):
    result = broker.buy("2330", qty=1000, price=500.0)
    assert result.success
    # 買入 1000 股 × 500 + 手續費 0.1425%
    expected_cost = 1000 * 500 * (1 + 0.001425)
    assert abs(broker.get_balance() - (1_000_000 - expected_cost)) < 1.0

def test_sell_increases_balance(broker):
    broker.buy("2330", qty=1000, price=500.0)
    result = broker.sell("2330", qty=1000, price=550.0)
    assert result.success

def test_sell_fails_when_no_position(broker):
    result = broker.sell("2330", qty=1000, price=500.0)
    assert not result.success
    assert result.error_msg is not None

def test_get_positions_reflects_holdings(broker):
    broker.buy("2330", qty=1000, price=500.0)
    positions = broker.get_positions()
    assert len(positions) == 1
    assert positions[0].ticker == "2330"
    assert positions[0].qty == 1000
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_paper.py -v
```

- [ ] **Step 3: 實作 orders/base.py**

```python
# orders/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OrderResult:
    success: bool
    order_id: str
    filled_price: float
    error_msg: str | None = None


@dataclass
class Position:
    ticker: str
    qty: int
    avg_price: float


class OrderBase(ABC):
    @abstractmethod
    def buy(self, ticker: str, qty: int, price: float) -> OrderResult: ...

    @abstractmethod
    def sell(self, ticker: str, qty: int, price: float) -> OrderResult: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_balance(self) -> float: ...
```

- [ ] **Step 4: 實作 orders/paper.py**

```python
# orders/paper.py
import uuid
from orders.base import OrderBase, OrderResult, Position

COMMISSION = 0.001425   # 買賣各 0.1425%
STT = 0.003             # 證交稅 0.3%（僅賣出）
SLIPPAGE = 0.001        # 滑點 0.1%


class PaperBroker(OrderBase):
    def __init__(self, initial_capital: float):
        self._balance = initial_capital
        self._positions: dict[str, Position] = {}

    def buy(self, ticker: str, qty: int, price: float) -> OrderResult:
        fill_price = price * (1 + SLIPPAGE)
        cost = fill_price * qty * (1 + COMMISSION)
        if cost > self._balance:
            return OrderResult(False, "", 0.0, "Insufficient balance")
        self._balance -= cost
        if ticker in self._positions:
            pos = self._positions[ticker]
            total_qty = pos.qty + qty
            avg = (pos.avg_price * pos.qty + fill_price * qty) / total_qty
            self._positions[ticker] = Position(ticker, total_qty, avg)
        else:
            self._positions[ticker] = Position(ticker, qty, fill_price)
        return OrderResult(True, str(uuid.uuid4()), fill_price)

    def sell(self, ticker: str, qty: int, price: float) -> OrderResult:
        if ticker not in self._positions or self._positions[ticker].qty < qty:
            return OrderResult(False, "", 0.0, f"No position for {ticker}")
        fill_price = price * (1 - SLIPPAGE)
        proceeds = fill_price * qty * (1 - COMMISSION - STT)
        self._balance += proceeds
        pos = self._positions[ticker]
        new_qty = pos.qty - qty
        if new_qty == 0:
            del self._positions[ticker]
        else:
            self._positions[ticker] = Position(ticker, new_qty, pos.avg_price)
        return OrderResult(True, str(uuid.uuid4()), fill_price)

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_balance(self) -> float:
        return self._balance
```

- [ ] **Step 5: 建立 orders/broker.py（stub）**

```python
# orders/broker.py
import os
from orders.base import OrderBase, OrderResult, Position


class RealBroker(OrderBase):
    """
    預留真實券商 API 介面（Fubon / 永豐金）。
    實際使用時設定 .env 的 BROKER_API_KEY 與 BROKER_API_SECRET。
    """
    def __init__(self):
        self._api_key = os.getenv("BROKER_API_KEY", "")
        self._api_secret = os.getenv("BROKER_API_SECRET", "")

    def buy(self, ticker: str, qty: int, price: float) -> OrderResult:
        raise NotImplementedError("Real broker API not yet integrated")

    def sell(self, ticker: str, qty: int, price: float) -> OrderResult:
        raise NotImplementedError("Real broker API not yet integrated")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("Real broker API not yet integrated")

    def get_balance(self) -> float:
        raise NotImplementedError("Real broker API not yet integrated")
```

- [ ] **Step 6: 執行測試確認 PASS**

```bash
pytest tests/test_paper.py -v
```

Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add orders/base.py orders/paper.py orders/broker.py tests/test_paper.py
git commit -m "feat: order abstraction, paper broker with commission/STT/slippage"
```

---

## Task 10: 回測引擎 (backtest/engine.py + report.py)

**Files:**
- Create: `backtest/engine.py`
- Create: `backtest/report.py`
- Create: `tests/test_backtest.py`

- [ ] **Step 1: 寫測試**

```python
# tests/test_backtest.py
import pandas as pd
import pytest
from backtest.engine import BacktestEngine

def make_price_df(closes):
    idx = pd.date_range("2020-01-02", periods=len(closes), freq="B")
    return pd.DataFrame({
        "Open": closes, "High": [c*1.02 for c in closes],
        "Low": [c*0.98 for c in closes],
        "Close": closes, "Volume": [100_000]*len(closes)
    }, index=idx)

def test_backtest_returns_stats_dict():
    closes = list(range(100, 200)) + list(range(200, 100, -1))
    df = make_price_df(closes)
    engine = BacktestEngine(initial_cash=1_000_000)
    stats = engine.run(df, ticker="2330")
    assert "total_return" in stats
    assert "max_drawdown" in stats
    assert "sharpe_ratio" in stats
    assert "win_rate" in stats
    assert "trades" in stats

def test_max_drawdown_is_negative_or_zero():
    closes = list(range(100, 200)) + list(range(200, 100, -1))
    df = make_price_df(closes)
    engine = BacktestEngine(initial_cash=1_000_000)
    stats = engine.run(df, ticker="2330")
    assert stats["max_drawdown"] <= 0.0

def test_backtest_report_creates_html_and_csv(tmp_path):
    from backtest.report import BacktestReport
    reporter = BacktestReport(reports_dir=str(tmp_path))
    stats = {
        "total_return": 0.15, "max_drawdown": -0.05, "sharpe_ratio": 1.2,
        "win_rate": 0.6, "trade_count": 2,
        "trades": [{"reason": "stop_loss", "entry_price": 100.0,
                    "exit_price": 93.0, "pnl_pct": -0.07}],
    }
    html_path = reporter.save("2330", stats)
    assert html_path.endswith(".html")
    from pathlib import Path
    assert Path(html_path).exists()
    csv_files = list(tmp_path.glob("*.csv"))
    assert len(csv_files) == 1

def test_backtest_respects_initial_cash():
    closes = [100] * 100
    df = make_price_df(closes)
    engine = BacktestEngine(initial_cash=500_000)
    stats = engine.run(df, ticker="2330")
    assert stats is not None
```

- [ ] **Step 2: 執行測試確認 FAIL**

```bash
pytest tests/test_backtest.py -v
```

- [ ] **Step 3: 實作 backtest/engine.py**

```python
# backtest/engine.py
import pandas as pd
import numpy as np
from signals.technical import TechnicalSignals
from signals.volume import VolumeSignals
from signals.composite import CompositeScore, SignalStrength
from strategy.entry import EntryFilter
from strategy.exit import ExitSignal

COMMISSION = 0.001425
STT = 0.003
SLIPPAGE = 0.001
DEFAULT_CONFIG = {
    "thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8},
    "position": {"size_pct": 0.10, "max_positions": 8},
    "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
             "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
             "time_stop_days": 20},
}


class BacktestEngine:
    def __init__(self, initial_cash: float = 1_000_000, config: dict = None):
        self._cash = initial_cash
        self._cfg = config or DEFAULT_CONFIG

    def run(self, df: pd.DataFrame, ticker: str) -> dict:
        warmup = 90
        if len(df) < warmup:
            return {"error": "insufficient_data"}

        cash = self._cash
        position_qty = 0
        entry_price = 0.0
        entry_day = 0
        tp1_triggered = False
        trades = []
        equity_history = []

        for i in range(warmup, len(df)):
            window = df.iloc[:i+1]
            close = window["Close"].iloc[-1]

            if position_qty == 0:
                # 評估進場
                tech = TechnicalSignals(window)
                t_score, _ = tech.score()
                vol = VolumeSignals(window)
                v_score, _ = vol.score()
                cs = CompositeScore(tech_score=t_score, vol_score=v_score, chips_score=None)
                ef = EntryFilter(config=self._cfg)
                if ef.should_enter(cs, window):
                    # 隔日開盤進場（用今日收盤模擬）
                    fill = close * (1 + 0.005 + SLIPPAGE)
                    pos_value = cash * self._cfg["position"]["size_pct"]
                    qty = int(pos_value / fill / 1000) * 1000  # 整張
                    if qty > 0:
                        cost = fill * qty * (1 + COMMISSION)
                        cash -= cost
                        position_qty = qty
                        entry_price = fill
                        entry_day = i
                        tp1_triggered = False
            else:
                # 評估出場
                es = ExitSignal(entry_price=entry_price, config=self._cfg)
                es._tp1_triggered = tp1_triggered
                tech = TechnicalSignals(window)
                t_score, _ = tech.score()
                vol = VolumeSignals(window)
                v_score, _ = vol.score()
                cs = CompositeScore(tech_score=t_score, vol_score=v_score, chips_score=None)
                action = es.check(close, i - entry_day, cs.total)
                if action["exit"]:
                    if action["reason"] == "take_profit_1":
                        tp1_triggered = True
                    sell_qty = int(position_qty * action["qty_pct"])
                    fill = close * (1 - SLIPPAGE)
                    proceeds = fill * sell_qty * (1 - COMMISSION - STT)
                    pnl = (fill - entry_price) / entry_price
                    cash += proceeds
                    position_qty -= sell_qty
                    trades.append({"reason": action["reason"], "pnl_pct": pnl,
                                   "entry_price": entry_price, "exit_price": fill})
                    if position_qty == 0:
                        entry_price = 0.0

            # Track equity
            equity_history.append(cash + position_qty * df["Close"].iloc[i])

        # 平倉剩餘
        if position_qty > 0:
            last_close = df["Close"].iloc[-1]
            proceeds = last_close * position_qty * (1 - COMMISSION - STT - SLIPPAGE)
            cash += proceeds

        total_return = (cash - self._cash) / self._cash
        win_rate = sum(1 for t in trades if t["pnl_pct"] > 0) / len(trades) if trades else 0
        pnls = [t["pnl_pct"] for t in trades]
        sharpe = (np.mean(pnls) / np.std(pnls) * np.sqrt(252)) if len(pnls) > 1 and np.std(pnls) > 0 else 0

        # Max Drawdown from equity curve
        equity_curve = np.array(equity_history)
        rolling_max = np.maximum.accumulate(equity_curve)
        drawdowns = (equity_curve - rolling_max) / rolling_max
        max_drawdown = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0

        return {
            "total_return": round(total_return, 4),
            "final_cash": round(cash, 2),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe, 4),
            "win_rate": round(win_rate, 4),
            "trade_count": len(trades),
            "trades": trades,
        }
```

- [ ] **Step 4: 實作 backtest/report.py**

```python
# backtest/report.py
import csv
from pathlib import Path
from datetime import datetime


class BacktestReport:
    def __init__(self, reports_dir: str = "reports/"):
        self._dir = Path(reports_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, ticker: str, stats: dict) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"backtest_{ticker}_{ts}"

        # CSV 交易明細
        csv_path = self._dir / f"{stem}.csv"
        trades = stats.get("trades", [])
        if trades:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=trades[0].keys())
                writer.writeheader()
                writer.writerows(trades)

        # HTML 報告
        html_path = self._dir / f"{stem}.html"
        rows = "".join(
            f"<tr><td>{t['reason']}</td><td>{t['entry_price']:.2f}</td>"
            f"<td>{t['exit_price']:.2f}</td><td>{t['pnl_pct']*100:.2f}%</td></tr>"
            for t in trades
        )
        html = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>回測報告 {ticker}</title>
<style>body{{font-family:sans-serif;padding:20px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;text-align:right}}
th{{background:#f2f2f2}}</style></head><body>
<h1>回測報告：{ticker}</h1>
<table><tr><th>指標</th><th>數值</th></tr>
<tr><td>總報酬率</td><td>{stats['total_return']*100:.2f}%</td></tr>
<tr><td>最大回撤</td><td>{stats['max_drawdown']*100:.2f}%</td></tr>
<tr><td>夏普比率</td><td>{stats['sharpe_ratio']:.4f}</td></tr>
<tr><td>勝率</td><td>{stats['win_rate']*100:.1f}%</td></tr>
<tr><td>交易次數</td><td>{stats['trade_count']}</td></tr>
</table>
<h2>交易明細</h2>
<table><tr><th>出場原因</th><th>買入價</th><th>賣出價</th><th>損益</th></tr>
{rows}</table></body></html>"""
        html_path.write_text(html, encoding="utf-8")
        return str(html_path)
```

- [ ] **Step 5: 執行測試確認 PASS**

```bash
pytest tests/test_backtest.py -v
```

Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backtest/engine.py backtest/report.py tests/test_backtest.py
git commit -m "feat: backtest engine with Taiwan transaction costs and report generation"
```

---

## Task 11: CLI 入口 (main.py)

**Files:**
- Create: `main.py`

- [ ] **Step 1: 實作 main.py**

```python
#!/usr/bin/env python3
# main.py
import argparse
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()
console = Console()


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def cmd_scan(args, cfg):
    from data.fetcher import Fetcher
    from signals.technical import TechnicalSignals
    from signals.volume import VolumeSignals
    from signals.chips import ChipsSignals
    from signals.composite import CompositeScore, SignalStrength
    from datetime import date, timedelta

    token = os.getenv("FINMIND_TOKEN", "")
    fetcher = Fetcher(
        cache_dir=cfg["data"]["cache_dir"],
        finmind_token=token,
        max_requests=cfg["data"]["max_api_requests_per_day"],
    )
    warmup_days = cfg["data"].get("warmup_days", 90)
    chips_start = (date.today() - timedelta(days=warmup_days)).strftime("%Y-%m-%d")
    watchlist = cfg["watchlist"]
    chips_ok = fetcher.can_fetch_chips(len(watchlist))
    if not chips_ok:
        console.print("[yellow]警告：FinMind 配額不足，本次掃描略過籌碼訊號[/yellow]")

    results = []
    for ticker in watchlist:
        df = fetcher.get_price(ticker)
        if df is None or len(df) < 90:
            continue
        t_score, _ = TechnicalSignals(df).score()
        v_score, _ = VolumeSignals(df).score()

        c_score = None
        if chips_ok:
            chips_data = fetcher.get_chips(ticker, start=chips_start)
            if chips_data:
                cs_sig = ChipsSignals(
                    inst_df=chips_data["institutional"],
                    margin_df=chips_data["margin"],
                    price_df=df,
                )
                c_score, _ = cs_sig.score()

        composite = CompositeScore(t_score, v_score, c_score)
        results.append((ticker, composite))

    results.sort(key=lambda x: x[1].total, reverse=True)

    table = Table(title="台股訊號掃描結果（Top 10）")
    table.add_column("代號", style="cyan")
    table.add_column("技術", justify="right")
    table.add_column("量能", justify="right")
    table.add_column("籌碼", justify="right")
    table.add_column("總分", justify="right", style="bold")
    table.add_column("強度")

    for ticker, cs in results[:10]:
        strength_str = {"strong": "[green]強訊號[/green]",
                        "watch": "[yellow]候選[/yellow]",
                        "weak": "[red]弱[/red]"}[cs.strength.value]
        table.add_row(
            ticker, str(cs.tech_score), str(cs.vol_score),
            str(cs.chips_score or "-"), str(cs.total), strength_str
        )
    console.print(table)


def cmd_backtest(args, cfg):
    from data.fetcher import Fetcher
    from backtest.engine import BacktestEngine
    from backtest.report import BacktestReport

    fetcher = Fetcher(cache_dir=cfg["data"]["cache_dir"])
    tickers = [args.ticker] if args.ticker else cfg["watchlist"]
    engine = BacktestEngine(initial_cash=1_000_000, config=cfg)
    reporter = BacktestReport()

    for ticker in tickers:
        df = fetcher.get_price(ticker, period="5y")
        if df is None:
            console.print(f"[red]無法取得 {ticker} 資料[/red]")
            continue
        if args.start:
            df = df[df.index >= args.start]
        stats = engine.run(df, ticker=ticker)
        path = reporter.save(ticker, stats)
        console.print(f"[cyan]{ticker}[/cyan] 報酬率: [bold]{stats['total_return']*100:.2f}%[/bold] "
                      f"勝率: {stats['win_rate']*100:.1f}% 報告: {path}")


_paper_broker = None  # module-level singleton for paper session


def _get_paper_broker(cfg: dict):
    global _paper_broker
    if _paper_broker is None:
        from orders.paper import PaperBroker
        _paper_broker = PaperBroker(initial_capital=1_000_000)
    return _paper_broker


def cmd_paper(args, cfg):
    from data.fetcher import Fetcher
    from signals.technical import TechnicalSignals
    from signals.volume import VolumeSignals
    from signals.composite import CompositeScore
    from strategy.entry import EntryFilter
    from strategy.exit import ExitSignal

    broker = _get_paper_broker(cfg)
    fetcher = Fetcher(cache_dir=cfg["data"]["cache_dir"])
    ticker = args.ticker

    df = fetcher.get_price(ticker)
    if df is None:
        console.print(f"[red]無法取得 {ticker} 資料[/red]")
        return

    tech_score, _ = TechnicalSignals(df).score()
    vol_score, _ = VolumeSignals(df).score()
    cs = CompositeScore(tech_score, vol_score, None)
    ef = EntryFilter(config=cfg)

    if ef.should_enter(cs, df):
        price = df["Close"].iloc[-1]
        capital = broker.get_balance() * cfg["position"]["size_pct"]
        qty = int(capital / price / 1000) * 1000
        if qty > 0:
            result = broker.buy(ticker, qty, price)
            if result.success:
                console.print(f"[green]紙上買入 {ticker} {qty} 股 @ {result.filled_price:.2f}[/green]")
            else:
                console.print(f"[red]買入失敗：{result.error_msg}[/red]")
        else:
            console.print(f"[yellow]{ticker} 資金不足開倉[/yellow]")
    else:
        console.print(f"[yellow]{ticker} 訊號不足（{cs.total}/25），不進場[/yellow]")


def cmd_positions(args, cfg):
    broker = _get_paper_broker(cfg)
    positions = broker.get_positions()
    if not positions:
        console.print("[yellow]目前無持倉[/yellow]")
        return
    from rich.table import Table
    table = Table(title="紙上交易持倉")
    table.add_column("代號")
    table.add_column("數量", justify="right")
    table.add_column("均價", justify="right")
    table.add_column("現值（估）", justify="right")
    for pos in positions:
        table.add_row(pos.ticker, str(pos.qty), f"{pos.avg_price:.2f}", "-")
    console.print(table)
    console.print(f"可用現金：{broker.get_balance():,.0f} NTD")


def main():
    parser = argparse.ArgumentParser(description="coin_war 台股訊號分析系統")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", help="掃描觀察清單訊號")

    bt = sub.add_parser("backtest", help="回測")
    bt.add_argument("--ticker", help="單一股票代號（如 2330）")
    bt.add_argument("--all", action="store_true", help="回測所有觀察清單")
    bt.add_argument("--start", default="2020-01-01", help="回測起始日期")

    pp = sub.add_parser("paper", help="紙上交易")
    pp.add_argument("--ticker", required=True)

    sub.add_parser("positions", help="顯示持倉")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "scan":
        cmd_scan(args, cfg)
    elif args.command == "backtest":
        cmd_backtest(args, cfg)
    elif args.command == "paper":
        cmd_paper(args, cfg)
    elif args.command == "positions":
        cmd_positions(args, cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 執行 help 確認可運行**

```bash
python main.py --help
```

Expected: 顯示 scan / backtest / paper / positions 指令說明

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: CLI entrypoint with scan/backtest/paper/positions commands"
```

---

## Task 12: 整合測試 + 最終驗證

**Files:**
- 無新檔案，驗證所有現有測試

- [ ] **Step 1: 執行全部測試**

```bash
pytest tests/ -v --tb=short
```

Expected: 全部 pass，無 error

- [ ] **Step 2: 快速 smoke test — 掃描（需設定 .env）**

```bash
cp .env.example .env
# 填入 FINMIND_TOKEN（可先用空值測試技術面訊號）
python main.py scan
```

Expected: 顯示訊號掃描表格，無 crash

- [ ] **Step 3: 快速 smoke test — 回測**

```bash
python main.py backtest --ticker 2330 --start 2022-01-01
```

Expected: 顯示報酬率、勝率，並在 reports/ 產出 JSON

- [ ] **Step 4: Final Commit**

```bash
git add -A
git commit -m "feat: complete Taiwan stock signal analysis system v1.0"
```

---

## 完成後下一步

1. 在 `.env` 填入真實 FinMind token 以啟用籌碼訊號
2. 擴充 `config/settings.yaml` 觀察清單至 50–200 支股票
3. 執行完整回測評估策略績效
4. 真實下單時，實作 `orders/broker.py` 串接券商 API
