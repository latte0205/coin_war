# Crypto Cross-Exchange Arbitrage (搬磚) Design Spec

## Goal

Add a fully automated cross-exchange cryptocurrency arbitrage system to `coin_war`, supporting real execution, live paper trading, and historical backtesting via L2 orderbook replay.

---

## Scope

This spec covers one self-contained module: `crypto/`. It does not modify the existing Taiwan stock signal system.

---

## Architecture

### New directory structure

```
crypto/
├── __init__.py
├── exchanges/
│   ├── __init__.py
│   ├── base.py           # Abstract exchange interface
│   ├── binance.py
│   ├── okx.py
│   ├── bybit.py
│   ├── max_exchange.py   # Taiwan MAX exchange
│   └── bitopro.py        # Taiwan BitoPro
├── scanner.py            # WebSocket price feed manager + spread detection
├── arbitrage.py          # Net profit calculation after fees
├── executor.py           # Simultaneous dual-leg order execution
├── position_sizer.py     # Trade size calculation
├── monitor.py            # Main event loop (real / dry_run modes)
└── backtest/
    ├── __init__.py
    ├── downloader.py     # Download Binance L2 historical orderbook snapshots
    ├── replayer.py       # Replay orderbook data to simulate arbitrage
    └── arb_report.py     # Backtest result statistics and HTML report
config/
└── crypto_settings.yaml  # All crypto arbitrage configuration
```

---

## Components

### `exchanges/base.py`

Abstract interface all exchange adapters must implement:

```python
class BaseExchange(ABC):
    name: str

    async def get_tradable_pairs(self) -> list[str]
    async def subscribe_orderbook(self, pairs: list[str], callback: Callable) -> None
    async def get_balance(self, asset: str) -> float
    async def place_market_order(self, pair: str, side: str, amount_usdt: float) -> OrderResult
    def taker_fee(self) -> float  # e.g. 0.001 for 0.1%
    def withdraw_fee(self, asset: str) -> float  # for future use
```

`OrderResult` dataclass:
```python
@dataclass
class OrderResult:
    success: bool
    exchange: str
    pair: str
    side: str
    filled_price: float
    filled_amount: float
    error_msg: str = ""
```

### `exchanges/*.py` — Individual adapters

Each adapter implements `BaseExchange` using the exchange's official SDK or REST + WebSocket API. Fee rates are hardcoded per exchange (configurable override in yaml):

| Exchange | Taker Fee | WebSocket Library |
|----------|-----------|-------------------|
| Binance  | 0.10%     | `python-binance` or `websockets` |
| OKX      | 0.10%     | `python-okx` |
| Bybit    | 0.10%     | `pybit` |
| MAX      | 0.15%     | REST + `websockets` |
| BitoPro  | 0.20%     | REST + `websockets` |

### `arbitrage.py`

Detects spread opportunities and calculates net profit:

```python
@dataclass
class ArbitrageOpportunity:
    pair: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float      # ask on buy exchange
    sell_price: float     # bid on sell exchange
    spread_pct: float     # net spread after both taker fees
    amount_usdt: float    # calculated trade size
    detected_at: datetime

def calculate_spread(buy_ex: BaseExchange, sell_ex: BaseExchange,
                     pair: str, ask: float, bid: float) -> float:
    """Returns net spread % after fees. Positive = profitable."""
    return (bid - ask) / ask - buy_ex.taker_fee() - sell_ex.taker_fee()
```

Both directions are always evaluated (A→B and B→A).

### `scanner.py`

Manages WebSocket subscriptions for all enabled exchanges. On each orderbook update:

1. Extract best `ask` (buy exchange) and `bid` (sell exchange) for the pair
2. Call `calculate_spread()` for both directions
3. If spread ≥ `min_spread_pct`: emit `ArbitrageOpportunity`
4. Apply cooldown: same pair cannot trigger again within `cooldown_seconds`

Dynamically computes common pairs: intersection of `get_tradable_pairs()` across all enabled exchanges.

### `position_sizer.py`

Calculates trade amount in USDT with dual constraint:

```python
def calculate_amount(balance_usdt: float, cfg: dict) -> float:
    min_amount = balance_usdt * cfg["position"]["min_balance_pct"]
    amount = min(cfg["position"]["max_usdt"], balance_usdt)
    amount = max(amount, min_amount)
    if amount < min_amount:
        return 0.0  # insufficient balance, skip
    return amount
```

Config keys: `max_usdt` (upper bound), `min_balance_pct` (lower bound as fraction of balance).

### `executor.py`

Executes both legs simultaneously using `asyncio.gather`:

```python
async def execute(opportunity: ArbitrageOpportunity,
                  buy_ex: BaseExchange, sell_ex: BaseExchange) -> ExecutionResult:
    buy_task  = buy_ex.place_market_order(opportunity.pair, "buy",  opportunity.amount_usdt)
    sell_task = sell_ex.place_market_order(opportunity.pair, "sell", opportunity.amount_usdt)
    buy_result, sell_result = await asyncio.gather(buy_task, sell_task, return_exceptions=True)
    # If either leg fails: log the failure, do NOT retry or hedge
    # Partial fill / exception = record as failed trade, move on
```

Single-leg failures are logged but not compensated. Attempting to hedge a failed leg creates directional exposure, which is worse than accepting the loss.

### `monitor.py`

Main event loop. Behaviour controlled by `dry_run` flag:

- `dry_run=False` (real mode): calls `executor.execute()` on each opportunity
- `dry_run=True` (paper trading): records the opportunity as a simulated trade, skips `executor`

Both modes write every opportunity to `reports/arb_log.csv`.

Rich console output shows:
- Current opportunities detected (pair, spread %, direction)
- Cumulative P&L (real or simulated)
- Balance per exchange

### `backtest/downloader.py`

Downloads historical L2 orderbook snapshots from `data.binance.vision` (free, official):

- Data format: daily compressed `.csv.gz` files with orderbook depth snapshots
- Other exchanges (OKX, MAX): download trade tick data as proxy for the opposing leg
- Stored in `cache/crypto/<exchange>/<pair>/<date>.parquet`

CLI: `python main.py arb --download-data --pair BTC/USDT --days 90`

### `backtest/replayer.py`

Replays downloaded orderbook data chronologically:

1. Load snapshots for both exchanges for the date range
2. Merge and sort by timestamp
3. Maintain current orderbook state per exchange
4. On each update: run the same `scanner.py` spread detection logic
5. On opportunity detected: simulate fill at recorded price with estimated slippage (0.05% default)
6. Record simulated trade result

### `backtest/arb_report.py`

Generates backtest statistics and HTML report (same format as existing `backtest/report.py`):

- Total return, win rate, max drawdown, Sharpe ratio
- Opportunities detected vs executed
- Best/worst pairs
- Hourly opportunity distribution chart

---

## Configuration (`config/crypto_settings.yaml`)

```yaml
exchanges:
  binance:
    api_key: ""
    api_secret: ""
    enabled: true
    taker_fee_override: null  # null = use default
  okx:
    api_key: ""
    api_secret: ""
    passphrase: ""
    enabled: false
  bybit:
    api_key: ""
    api_secret: ""
    enabled: false
  max_exchange:
    api_key: ""
    api_secret: ""
    enabled: true
  bitopro:
    api_key: ""
    api_secret: ""
    enabled: false

arbitrage:
  min_spread_pct: 0.005    # 0.5% minimum net spread after fees
  cooldown_seconds: 30     # per-pair cooldown after execution

position:
  max_usdt: 1000           # hard upper limit per trade
  min_balance_pct: 0.05    # lower bound: 5% of available balance

backtest:
  slippage_pct: 0.0005     # 0.05% estimated fill slippage
```

---

## CLI Integration (`main.py`)

```python
arb = sub.add_parser("arb", help="加密貨幣跨所套利（搬磚）")
arb.add_argument("--run",      action="store_true", help="全自動真實下單")
arb.add_argument("--dry-run",  action="store_true", help="即時 Paper Trading（不下單）")
arb.add_argument("--backtest", action="store_true", help="歷史回測")
arb.add_argument("--download-data", action="store_true", help="下載歷史 L2 資料")
arb.add_argument("--report",   action="store_true", help="顯示歷史套利紀錄")
arb.add_argument("--pair",     default=None, help="指定幣對（如 BTC/USDT）")
arb.add_argument("--start",    default=None, help="回測起始日期")
arb.add_argument("--end",      default=None, help="回測結束日期")
arb.add_argument("--days",     type=int, default=30, help="下載最近 N 天資料")
```

---

## Data Flow Summary

```
Real/Paper mode:
  WebSocket feeds → scanner.py → arbitrage.py → position_sizer.py
  → executor.py (real) OR log only (dry_run) → arb_log.csv

Backtest mode:
  downloader.py → cache/crypto/ → replayer.py → arbitrage.py
  → position_sizer.py → simulated fill → arb_report.py
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| WebSocket disconnect | Auto-reconnect with exponential backoff (max 5 retries) |
| Single leg order failure | Log failure, do NOT hedge, continue monitoring |
| Both legs fail | Log, continue |
| Insufficient balance | Skip trade, log warning |
| Exchange API rate limit | Back off, log warning |
| Missing L2 data for date | Skip that date in backtest, warn user |

---

## Out of Scope

- On-chain fund transfer / rebalancing between exchanges (future sub-project)
- Triangular arbitrage (A→B→C within one exchange)
- Futures/perpetual arbitrage (basis trading)
- CEX/DEX arbitrage
