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
│   ├── base.py           # Abstract exchange interface + shared dataclasses
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
└── crypto_settings.yaml  # Non-secret settings only (API keys in .env)
```

---

## Components

### `exchanges/base.py`

Defines the abstract interface, all shared dataclasses, and the canonical pair format.

**Canonical pair format:** `BASE/QUOTE` uppercase with slash, e.g. `BTC/USDT`, `ETH/USDT`.
Each adapter's `get_tradable_pairs()` returns pairs in this canonical format. Adapters handle internal symbol conversion (e.g. Binance `BTCUSDT` → `BTC/USDT`, OKX `BTC-USDT` → `BTC/USDT`) inside the adapter.

**Callback signature for `subscribe_orderbook`:**
```python
OrderbookCallback = Callable[[str, str, float, float], None]
# args: (exchange_name: str, pair: str, best_ask: float, best_bid: float)
```

**`place_market_order` sell-side semantics:** The `amount_usdt` parameter is always in quote currency (USDT). Each adapter internally converts to base currency for the actual API call:
```python
# Inside adapter before placing sell order:
base_amount = amount_usdt / current_best_bid  # adapter fetches from internal price cache
```
The adapter maintains an internal price cache from its WebSocket feed, so no extra REST call is needed.

**Abstract interface:**
```python
class BaseExchange(ABC):
    name: str  # lowercase identifier, e.g. "binance", "max"

    async def get_tradable_pairs(self) -> list[str]
    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None
    async def get_balance(self, asset: str) -> float
    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult
    async def close(self) -> None  # graceful shutdown, cancel WebSocket tasks
    def taker_fee(self) -> float
    def withdraw_fee(self, asset: str) -> float  # reserved, future use
    def current_price(self, pair: str) -> tuple[float, float] | None
    # Returns (best_ask, best_bid) from internal cache, or None if no data yet
```

**Shared dataclasses (defined in `base.py`, imported everywhere):**

```python
from datetime import datetime, timezone

@dataclass
class OrderResult:
    success: bool
    exchange: str
    pair: str
    side: str             # "buy" or "sell"
    filled_price: float   # 0.0 on failure
    filled_amount: float  # base currency units, 0.0 on failure
    error_msg: str = ""

@dataclass
class ExecutionResult:
    opportunity: "ArbitrageOpportunity"
    buy_result: OrderResult
    sell_result: OrderResult
    simulated: bool            # True if dry_run mode
    executed_at: datetime      # datetime.now(timezone.utc)
    realized_pnl_usdt: float   # 0.0 if either leg failed
    success: bool              # True only if both legs filled

    @property
    def failed(self) -> bool:
        return not self.success
```

### `exchanges/*.py` — Individual adapters

Each adapter implements `BaseExchange`. Fee rates are hardcoded defaults.

| Exchange  | Taker Fee | SDK / Library         |
|-----------|-----------|-----------------------|
| Binance   | 0.10%     | `python-binance`      |
| OKX       | 0.10%     | `python-okx`          |
| Bybit     | 0.10%     | `pybit`               |
| MAX       | 0.15%     | `aiohttp` + `websockets` |
| BitoPro   | 0.20%     | `aiohttp` + `websockets` |

**API keys** are loaded from environment variables, never stored in yaml:
```
BINANCE_API_KEY / BINANCE_API_SECRET
OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE
BYBIT_API_KEY / BYBIT_API_SECRET
MAX_API_KEY / MAX_API_SECRET
BITOPRO_API_KEY / BITOPRO_API_SECRET
```
The `crypto_settings.yaml` contains only `enabled: true/false` and `taker_fee_override` per exchange.

**WebSocket reconnect behaviour** (implemented in each adapter):
- On disconnect: exponential backoff starting at 1s, doubling to max 60s, max 5 retries
- After 5 failed retries: log error, mark exchange as unavailable, call `close()` on self
- `monitor.py` continues operating with remaining enabled exchanges and does not halt

### `arbitrage.py`

```python
@dataclass
class ArbitrageOpportunity:
    pair: str              # canonical format, e.g. "BTC/USDT"
    buy_exchange: str      # exchange name where we buy (cheaper ask)
    sell_exchange: str     # exchange name where we sell (higher bid)
    buy_price: float       # best ask on buy exchange at detection time
    sell_price: float      # best bid on sell exchange at detection time
    spread_pct: float      # net spread after both taker fees
    detected_at: datetime  # datetime.now(timezone.utc)
    # Note: amount_usdt is NOT part of this dataclass.
    # monitor.py calls position_sizer after receiving this, then passes
    # the amount separately to executor.execute().

def calculate_spread(buy_ex: BaseExchange, sell_ex: BaseExchange,
                     ask: float, bid: float) -> float:
    """Returns net spread % after fees. Positive = profitable."""
    return (bid - ask) / ask - buy_ex.taker_fee() - sell_ex.taker_fee()
```

Both directions (A→B and B→A) are evaluated on every orderbook update.

### `scanner.py`

Manages WebSocket subscriptions for all enabled exchanges.

**Startup sequence:**
1. Call `get_tradable_pairs()` on all enabled exchanges
2. Compute intersection → common pairs list
3. Subscribe all exchanges to the common pairs via `subscribe_orderbook`
4. Maintain in-memory dict: `prices[exchange_name][pair] = (best_ask, best_bid, updated_at)`

**Price staleness:** Prices older than 5 seconds are treated as unavailable. A pair is only evaluated if both exchanges have a price updated within 5 seconds.

**On each callback invocation:**
1. Update `prices[exchange_name][pair]` with new ask, bid, and `datetime.now(timezone.utc)`
2. For each pair where ≥ 2 exchanges have fresh prices (≤ 5s old): evaluate both directions
3. If spread ≥ `min_spread_pct`: check cooldown for `(pair, buy_exchange, sell_exchange)` triplet
4. If not on cooldown: emit `ArbitrageOpportunity` to `monitor.py`

**Cooldown** is keyed on `(pair, buy_exchange, sell_exchange)` triplet. BTC/USDT Binance→MAX and BTC/USDT MAX→Binance are independent cooldowns.

### `position_sizer.py`

```python
def calculate_amount(balance_usdt: float, cfg: dict) -> float:
    """
    Returns trade amount in USDT, or 0.0 if trade should be skipped.

    Rules (in priority order):
    1. If balance < min_usdt: return 0.0 (absolute floor)
    2. Compute desired range: [min_from_pct, max_usdt]
    3. amount = clamp(balance_usdt, low=min_from_pct, high=max_usdt)
       where high is always respected — amount never exceeds max_usdt
    """
    max_usdt       = cfg["position"]["max_usdt"]          # e.g. 1000
    min_balance_pct = cfg["position"]["min_balance_pct"]  # e.g. 0.05
    min_usdt       = cfg["position"]["min_usdt"]          # e.g. 20

    if balance_usdt < min_usdt:
        return 0.0

    min_from_pct = balance_usdt * min_balance_pct     # lower bound from pct
    effective_min = min(min_from_pct, max_usdt)       # min can never exceed max
    amount = min(balance_usdt, max_usdt)              # cap at max_usdt
    amount = max(amount, effective_min)               # ensure at least effective_min
    return amount
    # Examples:
    #   balance=5000, max=1000, pct=5% → min_from_pct=250, amount=min(5000,1000)=1000 ✓
    #   balance=200,  max=1000, pct=5% → min_from_pct=10,  amount=min(200,1000)=200 ✓
    #   balance=15,   min_usdt=20      → return 0.0 ✓
```

Config keys:
- `max_usdt`: hard upper bound per trade (e.g. 1000)
- `min_balance_pct`: lower bound as fraction of balance (e.g. 0.05)
- `min_usdt`: absolute floor below which we skip (e.g. 20)

### `executor.py`

`execute()` takes `amount_usdt` separately (not inside `ArbitrageOpportunity`):

```python
async def execute(opportunity: ArbitrageOpportunity,
                  buy_ex: BaseExchange,
                  sell_ex: BaseExchange,
                  amount_usdt: float,
                  dry_run: bool = False) -> ExecutionResult:
    now = datetime.now(timezone.utc)

    if dry_run:
        buy_result = OrderResult(
            success=True, exchange=buy_ex.name, pair=opportunity.pair,
            side="buy", filled_price=opportunity.buy_price,
            filled_amount=amount_usdt / opportunity.buy_price)
        sell_result = OrderResult(
            success=True, exchange=sell_ex.name, pair=opportunity.pair,
            side="sell", filled_price=opportunity.sell_price,
            filled_amount=amount_usdt / opportunity.buy_price)
    else:
        buy_task  = buy_ex.place_market_order(opportunity.pair, "buy",  amount_usdt)
        sell_task = sell_ex.place_market_order(opportunity.pair, "sell", amount_usdt)
        raw = await asyncio.gather(buy_task, sell_task, return_exceptions=True)

        def _to_result(r, side: str, ex: BaseExchange) -> OrderResult:
            if isinstance(r, Exception):
                return OrderResult(success=False, exchange=ex.name,
                                   pair=opportunity.pair, side=side,
                                   filled_price=0.0, filled_amount=0.0,
                                   error_msg=str(r))
            return r  # already an OrderResult from the adapter

        buy_result  = _to_result(raw[0], "buy",  buy_ex)
        sell_result = _to_result(raw[1], "sell", sell_ex)

    success = buy_result.success and sell_result.success
    pnl = 0.0
    if success:
        # Use min of both filled amounts to avoid overstating P&L on partial fills
        matched_amount = min(buy_result.filled_amount, sell_result.filled_amount)
        gross = (sell_result.filled_price - buy_result.filled_price) * matched_amount
        fees  = (buy_ex.taker_fee() + sell_ex.taker_fee()) * amount_usdt
        pnl   = gross - fees

    return ExecutionResult(
        opportunity=opportunity,
        buy_result=buy_result,
        sell_result=sell_result,
        simulated=dry_run,
        executed_at=now,
        realized_pnl_usdt=pnl,
        success=success,
    )
```

Single-leg failures: logged, no hedge, continue monitoring.

### `monitor.py`

Main async event loop started from `main.py` via `asyncio.run(monitor.start(cfg, dry_run))`.

**Balance caching:** `monitor.py` fetches balances from all enabled exchanges on startup and refreshes every 30 seconds via an async background task. The cached balance for the buy exchange is what `position_sizer` receives. This avoids per-trade REST calls.

**Responsibilities:**
1. Initialise all enabled exchange adapters (load API keys from env)
2. Start balance refresh background task (every 30s)
3. Start `scanner.py` WebSocket subscriptions
4. On each `ArbitrageOpportunity`:
   a. Look up cached USDT balance for buy exchange
   b. Call `position_sizer.calculate_amount(balance, cfg)` → `amount_usdt`
   c. If `amount_usdt > 0`: call `executor.execute(opportunity, ..., amount_usdt, dry_run)`
   d. Append `ExecutionResult` to `reports/arb_log.csv`
   e. Set cooldown for `(pair, buy_ex, sell_ex)` triplet
5. On Ctrl-C: call `close()` on all exchange adapters, then exit

**Rich console:** Refreshes every second showing:
- Live opportunity table (pair, spread %, direction, age)
- Cumulative P&L (real or simulated)
- Balance per exchange (from cache)

### `arb_log.csv` schema

One row per `ExecutionResult`:

| Column | Type | Description |
|--------|------|-------------|
| `executed_at` | ISO datetime UTC | |
| `pair` | str | e.g. `BTC/USDT` |
| `buy_exchange` | str | |
| `sell_exchange` | str | |
| `buy_price` | float | ask at detection time |
| `sell_price` | float | bid at detection time |
| `spread_pct` | float | net spread after fees |
| `amount_usdt` | float | requested trade size |
| `buy_filled_price` | float | actual fill price, 0.0 on failure |
| `buy_filled_amount` | float | base currency, 0.0 on failure |
| `sell_filled_price` | float | actual fill price, 0.0 on failure |
| `sell_filled_amount` | float | base currency, 0.0 on failure |
| `realized_pnl_usdt` | float | 0.0 if failed or simulated |
| `success` | bool | both legs filled |
| `simulated` | bool | dry_run mode |
| `buy_error` | str | empty if success |
| `sell_error` | str | empty if success |

### `backtest/downloader.py`

Downloads and caches historical data for backtesting.

**Binance (primary exchange):** L2 orderbook depth snapshots from `data.binance.vision`.
- Actual file format (wide CSV): each row is one snapshot.
  Columns: `lastUpdateId, timestamp, asks[0].price, asks[0].qty, asks[1].price, asks[1].qty, ..., bids[0].price, bids[0].qty, ...`
  Only the top-of-book (level 0) ask and bid are used by the replayer.
- URL pattern: `https://data.binance.vision/data/spot/daily/depth/<BTCUSDT>/<BTCUSDT>-bookDepth-<YYYY-MM-DD>.zip`
- Stored as `cache/crypto/binance/<BTCUSDT>/<YYYY-MM-DD>.parquet` with columns `[timestamp_ms, best_ask, best_bid]`

**Other exchanges (opposing leg):** Since only Binance provides free L2 history, other exchanges use **trade tick data** as a proxy. The replayer converts the last trade price to a synthetic bid/ask:
```
synthetic_ask = last_price * 1.0002
synthetic_bid = last_price * 0.9998
```
This introduces minor (~0.04%) inaccuracy. Backtest reports display a disclaimer when tick-proxy data is used.

Stored as `cache/crypto/<exchange>/<pair_normalized>/<YYYY-MM-DD>.parquet`

CLI: `python main.py arb --download-data --pair BTC/USDT --days 90`

### `backtest/replayer.py`

Replays downloaded data chronologically to simulate arbitrage:

1. Load data for both exchanges for the date range
2. For non-Binance exchanges: apply synthetic bid/ask from tick data
3. Merge all updates into a single time-sorted event stream (key: `timestamp_ms`)
4. Maintain current `(ask, bid, updated_at)` state per exchange per pair
5. On each event: apply same 5-second staleness check as live scanner
6. Call `calculate_spread()` for both directions; if ≥ threshold and not on cooldown:
   - Apply `slippage_pct` to fill prices: `fill_ask = ask * (1 + slippage_pct)`, `fill_bid = bid * (1 - slippage_pct)`
   - Create simulated `ExecutionResult` via `executor.execute(..., dry_run=True)`
7. Collect all results → pass to `arb_report.py`

### `backtest/arb_report.py`

Generates HTML report (same visual style as `backtest/report.py`, different data schema):

**Statistics:**
- Total P&L (USDT), total return %
- Win rate (both legs filled and profitable)
- Max drawdown (cumulative P&L curve)
- Sharpe ratio (daily P&L series)
- Opportunities detected vs executed (fill rate)
- Best and worst pairs by P&L
- Hourly opportunity count heatmap

Disclaimer appended to report when any exchange used tick-proxy data instead of true L2 snapshots.

---

## Configuration (`config/crypto_settings.yaml`)

API keys are **not** stored here — use `.env` file.

```yaml
exchanges:
  binance:
    enabled: true
    taker_fee_override: null   # null = use hardcoded default (0.001)
  okx:
    enabled: false
    taker_fee_override: null
  bybit:
    enabled: false
    taker_fee_override: null
  max_exchange:
    enabled: true
    taker_fee_override: null
  bitopro:
    enabled: false
    taker_fee_override: null

arbitrage:
  min_spread_pct: 0.005      # 0.5% minimum net spread after fees
  cooldown_seconds: 30       # per (pair, buy_ex, sell_ex) triplet
  price_staleness_seconds: 5 # ignore prices older than this

position:
  max_usdt: 1000             # hard upper limit per trade
  min_balance_pct: 0.05      # lower bound: 5% of available balance
  min_usdt: 20               # absolute floor: skip if balance < this

monitor:
  balance_refresh_seconds: 30  # how often to refresh exchange balances

backtest:
  slippage_pct: 0.0005       # 0.05% estimated fill slippage
```

`.env` additions:
```
BINANCE_API_KEY=
BINANCE_API_SECRET=
OKX_API_KEY=
OKX_API_SECRET=
OKX_PASSPHRASE=
BYBIT_API_KEY=
BYBIT_API_SECRET=
MAX_API_KEY=
MAX_API_SECRET=
BITOPRO_API_KEY=
BITOPRO_API_SECRET=
```

---

## CLI Integration (`main.py`)

`asyncio.run()` is called inside `cmd_arb()`, keeping `main()` synchronous.
`--run` and `--dry-run` are mutually exclusive (enforced by `argparse`).

```python
def cmd_arb(args, cfg):
    import asyncio
    from crypto.monitor import start as arb_start

    if args.run or args.dry_run:
        asyncio.run(arb_start(cfg, dry_run=args.dry_run))
    elif args.backtest:
        from crypto.backtest.replayer import run_backtest
        asyncio.run(run_backtest(cfg, pair=args.pair, start=args.start, end=args.end))
    elif args.download_data:
        from crypto.backtest.downloader import download
        asyncio.run(download(pair=args.pair, days=args.days))
    elif args.report:
        from crypto.backtest.arb_report import print_report
        print_report("reports/arb_log.csv")

arb = sub.add_parser("arb", help="加密貨幣跨所套利（搬磚）")
mode = arb.add_mutually_exclusive_group()
mode.add_argument("--run",     action="store_true", help="全自動真實下單")
mode.add_argument("--dry-run", action="store_true", help="即時 Paper Trading（不下單）")
arb.add_argument("--backtest",      action="store_true", help="歷史回測")
arb.add_argument("--download-data", action="store_true", help="下載歷史 L2 資料")
arb.add_argument("--report",        action="store_true", help="顯示歷史套利紀錄")
arb.add_argument("--pair",  default=None, help="指定幣對（如 BTC/USDT）")
arb.add_argument("--start", default=None, help="回測起始日期 YYYY-MM-DD")
arb.add_argument("--end",   default=None, help="回測結束日期 YYYY-MM-DD")
arb.add_argument("--days",  type=int, default=30, help="下載最近 N 天資料")
```

---

## New Dependencies (`requirements.txt` additions)

```
python-binance>=1.0.19
python-okx>=0.3.0
pybit>=5.0.0
websockets>=12.0
aiohttp>=3.9.0
```

---

## Data Flow Summary

```
Real / Paper mode:
  .env API keys → exchange adapters
  WebSocket feeds → scanner.py (prices dict, staleness-checked)
  → arbitrage.py (calculate_spread, both directions, cooldown)
  → monitor.py: position_sizer(cached_balance) → amount_usdt
  → executor.execute(opportunity, amount_usdt, dry_run)
  → ExecutionResult → arb_log.csv + Rich console

Backtest mode:
  downloader.py → cache/crypto/<exchange>/<pair>/<date>.parquet
  → replayer.py (time-sorted events, synthetic bid/ask for tick data)
  → arbitrage.py + position_sizer.py
  → executor.execute(..., dry_run=True) → simulated ExecutionResult list
  → arb_report.py → reports/backtest_arb_<pair>_<date>.html
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| WebSocket disconnect | Exponential backoff 1s→2s→4s…60s, max 5 retries |
| 5 retries exhausted | Mark exchange unavailable, call `close()`, system continues on others |
| Price staleness (> 5s) | Skip pair for spread check until fresh update arrives |
| Single leg order failure | `OrderResult(success=False, filled_price=0.0, filled_amount=0.0, error_msg=...)` |
| Both legs fail | Log ExecutionResult with `success=False`, continue |
| balance < min_usdt | `position_sizer` returns 0.0, skip trade, log warning |
| Exchange API rate limit | Log warning, back off |
| Missing L2 data for date | Skip that date in backtest, warn user |
| Tick data used as proxy | Log warning, add disclaimer to backtest report |

---

## Out of Scope

- On-chain fund transfer / rebalancing between exchanges (future sub-project)
- Triangular arbitrage (A→B→C within one exchange)
- Futures/perpetual arbitrage (basis trading)
- CEX/DEX arbitrage
