# Taiwan Stock Signal Analysis System — Design Spec

**Date:** 2026-03-22
**Project:** coin_war
**Goal:** 全自動台股訊號分析、回測與下單輔助系統

---

## 1. 系統架構

```
coin_war/
├── config/
│   └── settings.yaml          # 股票清單、參數、API key（不 commit 機敏資訊）
├── data/
│   ├── fetcher.py             # yfinance + FinMind 資料抓取
│   └── cache.py               # 本地 parquet 快取（含過期檢查）
├── signals/
│   ├── technical.py           # KD、MACD、RSI、布林通道、均線
│   ├── volume.py              # 量能訊號（爆量突破、OBV）
│   ├── chips.py               # 籌碼面（外資/投信/自營買賣超）
│   └── composite.py           # 加權評分合成器
├── strategy/
│   ├── entry.py               # 進場規則（訊號閾值 → 買入條件）
│   └── exit.py                # 出場規則（停損/停利/訊號反轉）
├── backtest/
│   ├── engine.py              # backtesting.py 封裝
│   └── report.py              # 回測報告輸出（HTML + CSV）
├── orders/
│   ├── base.py                # 抽象介面 OrderBase（paper 與 broker 共用）
│   ├── paper.py               # 紙上交易模擬
│   └── broker.py              # 券商 API 介面（預留 Fubon/Sinopac）
├── reports/                   # 產出的報告檔案
├── tests/                     # 單元測試
├── main.py                    # CLI 入口
├── requirements.txt
└── .env.example               # API key 範本（不含真實值）
```

---

## 2. 資料層

### 2.1 價格資料 (yfinance)
- 抓取台股 OHLCV 日線
- 股票代號格式：`2330.TW`
- **快取策略：** 每個 ticker 存為 `cache/<ticker>.parquet`
- **過期規則：** 若快取最後一筆日期 < 最近交易日則重新抓取；交易日曆使用 `exchange_calendars` 的 `XTAI` 日曆（含假日、颱風停市）
- **資料品質：** 若 yfinance 回傳空 DataFrame 或缺 OHLCV 欄位，記錄 warning 並跳過該 ticker

### 2.2 籌碼資料 (FinMind API)
- 三大法人買賣超：`TaiwanStockInstitutionalInvestorsBuySell`
- 融資融券：`TaiwanStockMarginPurchaseShortSale`
- **API 限制：** 免費帳號每日 600 次請求
- **觀察清單規模：** 預設 200 支股票（可在 settings.yaml 調整）
- **降級策略（全量或全略）：** 每次掃描前先估算所需請求數（觀察清單數 × 2 資料集），若超過剩餘配額則**整個籌碼層跳過**，改以技術指標 + 量能訊號計分；不接受部分籌碼資料，避免清單前段股票因有籌碼分數而在排名上佔優勢，造成系統性偏差。報告中標注「籌碼資料不可用（配額不足）」
- **資料時間：** FinMind 籌碼資料為 **T 日收盤後發布**；系統一律使用 T-1 日籌碼資料計算 T 日訊號，避免 look-ahead bias

### 2.3 資料時序說明（防 look-ahead bias）
```
T-1 收盤後：
  → 抓取 T-1 價格、T-1 籌碼資料
  → 計算所有訊號
  → 產生 T 日候選清單

T 日開盤：
  → 以「T 日開盤價 + 0.5%」作為進場參考價
```

---

## 3. 訊號層

### 3.1 技術指標訊號 (signals/technical.py)
| 訊號 | 條件 | 分數 |
|---|---|---|
| KD 黃金交叉 | K 上穿 D（前一日 K < D，當日 K > D） | +2 |
| MACD 黃金交叉 | MACD 線上穿訊號線 | +2 |
| RSI 超賣反彈 | RSI 從 < 30 回升過 35 | +2 |
| 布林通道突破 | 收盤突破上軌（做為低權重趨勢確認輔助訊號） | +1 |
| 均線多頭排列 | 5MA > 10MA > 20MA > 60MA | +2 |

> 備注：KD 黃金交叉不限制 K 值位置，任意位置的交叉均計分，由其他訊號綜合判斷強弱。布林上軌突破為趨勢延續確認，非超買警示，權重刻意設低 (+1)。

### 3.2 量能訊號 (signals/volume.py)
| 訊號 | 條件 | 分數 |
|---|---|---|
| 爆量突破 | 成交量 > 20 日均量 × 2 且收陽線 | +3 |
| 縮量整理後放量 | 前 5 日成交量 < 20 日均量，當日量 > 20 日均量 × 1.5 | +2 |
| OBV 上升趨勢 | OBV 創近 10 日新高 | +1 |

### 3.3 籌碼訊號 (signals/chips.py)
| 訊號 | 條件 | 分數 |
|---|---|---|
| 外資連買 | 外資連續 3 日以上買超 | +3 |
| 投信連買 | 投信連續 2 日以上買超 | +2 |
| 法人合力買超 | 外資 + 投信同日雙買超 | +3 |
| 融資減少 + 股價上漲 | 融資餘額日減 > 1%，股價上漲 | +2 |

> 備注：籌碼訊號使用 T-1 日資料（見第 2.3 節），資料不可用時跳過此分類。

### 3.4 複合評分 (signals/composite.py)
- **最高分：25 分**（技術 9 + 量能 6 + 籌碼 10）
- **強訊號進場：≥ 14 分**
- **觀察候選：10–13 分**
- 每日掃描觀察清單（預設 200 支），輸出前 10 名

---

## 4. 策略層

### 4.1 進場規則 (strategy/entry.py)
1. 複合訊號分數 ≥ 14
2. 當日成交量 > **20 日均量 × 0.8**（相對流動性過濾，可在 settings.yaml 調整）
3. 股價 > 5 日均線（確認短期趨勢向上）
4. 進場價：隔日開盤 + 0.5%（隔日 T+1 開盤時執行）
5. **每筆倉位：** 總資金的 10%（最多同時持有 8 支）

### 4.2 出場規則 (strategy/exit.py)
- **停損：** 買入後跌破 -7%（固定停損，全倉出場）
- **分批停利：** +15% 時出場 50%，+20% 時出場剩餘 50%
- **訊號停損：** 複合分數跌至 < 6 時次日開盤出場（全倉）
- **時間停損：** 持有超過 20 個交易日且獲利 < +5% 則次日出場

### 4.3 倉位管理
| 參數 | 預設值 | 說明 |
|---|---|---|
| 單筆倉位 | 10% 總資金 | 固定比例 |
| 最大持倉數 | 8 支 | 超過則不開新倉 |
| 最大持倉比例 | 80% 總資金 | 保留 20% 現金緩衝 |

---

## 5. 回測層

### 5.1 回測框架
- 使用 `backtesting.py` 框架
- 回測期間：2020-01-01 至今
- 初始資金：1,000,000 NTD
- 手續費：0.1425% × 2（買賣）+ 0.3% 證交稅（賣出）
- 滑點：0.1%（模擬市場衝擊）
- **交易日曆：** `exchange_calendars` XTAI（含台灣假日）

### 5.2 報告指標
- 總報酬率、年化報酬率
- 最大回撤 (Max Drawdown)
- 夏普比率 (Sharpe Ratio)
- 勝率、平均盈虧比
- 每筆交易明細（進出場日期、價格、獲利）

---

## 6. 下單層

### 6.1 抽象介面 (orders/base.py)
```python
class OrderBase(ABC):
    def buy(self, ticker: str, qty: int, price: float) -> OrderResult: ...
    def sell(self, ticker: str, qty: int, price: float) -> OrderResult: ...
    def get_positions(self) -> list[Position]: ...
    def get_balance(self) -> float: ...

@dataclass
class OrderResult:
    success: bool
    order_id: str
    filled_price: float
    error_msg: str | None  # None if success
```

### 6.2 紙上交易 (orders/paper.py)
- 繼承 `OrderBase`
- 模擬買賣、手續費、滑點
- 持倉狀態存於記憶體 dict

### 6.3 真實下單介面 (orders/broker.py)
- 繼承 `OrderBase`
- 預留 Fubon API / 永豐金 API hook
- 需在 `.env` 設定 `BROKER_API_KEY`、`BROKER_API_SECRET`

---

## 7. 設定檔 (config/settings.yaml)

```yaml
watchlist:
  - "2330"   # 台積電
  - "2317"   # 鴻海
  # ... 最多 200 支

thresholds:
  strong_signal: 14
  watch_signal: 10
  exit_signal: 6
  volume_filter_ratio: 0.8  # 相對 20日均量

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

# API keys 請設定於 .env 檔案，勿 commit 至 git
```

---

## 8. 技術棧

```
Python 3.11+
yfinance >= 0.2
pandas, numpy
ta (technical analysis library)
FinMind (PyFinmind)
backtesting.py
exchange_calendars
rich (CLI 美化)
pyyaml
python-dotenv
pytest
```

---

## 9. 使用流程

```bash
# 安裝
pip install -r requirements.txt
cp .env.example .env  # 填入 FinMind token

# 每日掃描訊號（使用最近交易日資料）
python main.py scan

# 回測某股票
python main.py backtest --ticker 2330 --start 2020-01-01

# 回測所有觀察清單
python main.py backtest --all --start 2022-01-01

# 紙上交易模式
python main.py paper --ticker 2330

# 顯示現有持倉
python main.py positions
```

---

## 10. 安全注意事項

- `.env` 加入 `.gitignore`，API key 不 commit
- `settings.yaml` 中不含任何憑證
- 真實下單前請務必在紙上交易模式驗證策略
