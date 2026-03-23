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
Each adapter's `get_tradable_pairs()` returns pairs in this canonical format. Adapters handle internal symbol conversion (e.g. Binance `BTCUSDT` → `BTC/USDT`, OKX `BTC-USDT` → `BTC/USDT`) internally.

**Callback signature for `subscribe_orderbook`:**
```python
from collections.abc import Callable

OrderbookCallback = Callable[[str, str, float, float], None]
# args: (exchange_name: str, pair: str, best_ask: float, best_bid: float)
```

**`place_market_order` sell-side semantics:** The `amount_usdt` parameter is always in quote currency (USDT) for both buy and sell. Each adapter internally converts to base currency for the actual API call using the adapter's internal price cache:
```python
# Inside adapter before placing sell order:
base_amount = amount_usdt / self._price_cache[pair]["bid"]
```
The adapter maintains an internal price cache populated from its WebSocket feed, so no extra REST call is needed.

**`taker_fee_override` wiring:** Each adapter constructor accepts the exchange config dict and reads `taker_fee_override` from it. If non-null, it overrides the hardcoded default:
```python
class BinanceExchange(BaseExchange):
    def __init__(self, exchange_cfg: dict):
        self._fee = exchange_cfg.get("taker_fee_override") or 0.001
```
The `exchange_cfg` is the per-exchange section from `crypto_settings.yaml` (e.g. `cfg["exchanges"]["binance"]`).

**Abstract interface:**
```python
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timezone

class BaseExchange(ABC):
    name: str  # lowercase identifier, e.g. "binance", "max"

    @abstractmethod
    async def get_tradable_pairs(self) -> list[str]: ...

    @abstractmethod
    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None: ...

    @abstractmethod
    async def get_balance(self, asset: str) -> float: ...

    @abstractmethod
    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> "OrderResult": ...

    @abstractmethod
    async def close(self) -> None: ...
    # Cancels WebSocket tasks; called on graceful shutdown or after 5 reconnect failures

    def taker_fee(self) -> float: ...     # returns effective fee (override or default)
    def withdraw_fee(self, asset: str) -> float:
        return 0.0  # not abstract; adapters may leave this as the default — not yet used

    def current_price(self, pair: str) -> tuple[float, float] | None:
        # Returns (best_ask, best_bid) from internal cache, or None if no data yet
        ...
```

**Shared dataclasses (defined in `base.py`, imported everywhere):**

```python
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
    amount_usdt: float         # trade size used (carried here for CSV logging)
    simulated: bool            # True if dry_run mode
    executed_at: datetime      # datetime.now(timezone.utc)
    realized_pnl_usdt: float   # computed for both real and dry_run; 0.0 if either leg failed
    success: bool              # True only if both legs filled

    @property
    def failed(self) -> bool:
        return not self.success
```

### `exchanges/*.py` — Individual adapters

Each adapter implements `BaseExchange`. Constructor signature: `__init__(self, exchange_cfg: dict)`.

| Exchange  | Taker Fee | SDK / Library            |
|-----------|-----------|--------------------------|
| Binance   | 0.10%     | `python-binance`         |
| OKX       | 0.10%     | `python-okx`             |
| Bybit     | 0.10%     | `pybit`                  |
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

**WebSocket reconnect behaviour** (implemented in each adapter):
- On disconnect: exponential backoff 1s → 2s → 4s … 60s, max 5 retries
- After 5 failed retries: call `self.close()`, mark self unavailable
- `monitor.py` continues operating with remaining enabled exchanges

### `arbitrage.py`

```python
@dataclass
class ArbitrageOpportunity:
    pair: str              # canonical format, e.g. "BTC/USDT"
    buy_exchange: str
    sell_exchange: str
    buy_price: float       # best ask on buy exchange at detection time
    sell_price: float      # best bid on sell exchange at detection time
    spread_pct: float      # net spread after both taker fees
    detected_at: datetime  # datetime.now(timezone.utc)
    # NOTE: amount_usdt is intentionally absent.
    # monitor.py calls position_sizer after receiving this opportunity,
    # then passes amount_usdt separately to executor.execute().

def calculate_spread(buy_ex: BaseExchange, sell_ex: BaseExchange,
                     ask: float, bid: float) -> float:
    """Returns net spread % after fees. Positive = profitable."""
    return (bid - ask) / ask - buy_ex.taker_fee() - sell_ex.taker_fee()
```

Both directions (A→B and B→A) evaluated on every orderbook update.

### `scanner.py`

Manages WebSocket subscriptions for all enabled exchanges.

**Scanner-to-monitor communication:** scanner uses an `asyncio.Queue[ArbitrageOpportunity]` passed in at construction. `monitor.py` creates the queue, passes it to `Scanner`, and calls `await queue.get()` in its main loop.

**Startup:**
1. `get_tradable_pairs()` on all enabled exchanges → compute intersection
2. Subscribe all exchanges to common pairs via `subscribe_orderbook`
3. Maintain `prices[exchange_name][pair] = (best_ask, best_bid, updated_at: datetime UTC)`

**Price staleness:** prices older than `price_staleness_seconds` (config) are excluded from spread checks. Compare: `(datetime.now(timezone.utc) - updated_at).total_seconds() > price_staleness_seconds`.

**Cooldown dict** is owned by scanner: `_cooldowns: dict[tuple, datetime]` keyed on `(pair, buy_exchange, sell_exchange)`. `monitor.py` calls `scanner.set_cooldown(pair, buy_ex, sell_ex)` after each execution.

**On each callback:**
1. Update `prices[exchange_name][pair]` with `(ask, bid, datetime.now(timezone.utc))`
2. For each pair with ≥ 2 fresh prices: evaluate both directions
3. If spread ≥ `min_spread_pct` and not on cooldown: `await queue.put(opportunity)`

Both directions are independent cooldowns.

### `position_sizer.py`

```python
def calculate_amount(balance_usdt: float, cfg: dict) -> float:
    """
    Returns trade size in USDT, or 0.0 if trade should be skipped.

    Rules:
    1. If balance < min_usdt: return 0.0
    2. Desired range: [effective_min, max_usdt]
       effective_min = min(balance * min_balance_pct, max_usdt)  — min never exceeds max
    3. amount = clamp(balance, low=effective_min, high=max_usdt)
    """
    max_usdt        = cfg["position"]["max_usdt"]
    min_balance_pct = cfg["position"]["min_balance_pct"]
    min_usdt        = cfg["position"]["min_usdt"]

    if balance_usdt < min_usdt:
        return 0.0

    effective_min = min(balance_usdt * min_balance_pct, max_usdt)
    amount = min(balance_usdt, max_usdt)    # never exceed max_usdt
    amount = max(amount, effective_min)     # ensure at least effective_min
    return amount
    # Examples:
    #   balance=5000, max=1000, pct=5% → effective_min=250, amount=1000 ✓ (1000≤max)
    #   balance=200,  max=1000, pct=5% → effective_min=10,  amount=200  ✓
    #   balance=15,   min_usdt=20      → return 0.0 ✓
```

Config read path: `cfg["position"]["max_usdt"]` etc. — `cfg` is the crypto config dict, not the main settings.

### `executor.py`

`execute()` receives `amount_usdt` as a separate parameter (not inside `ArbitrageOpportunity`).

```python
async def execute(opportunity: ArbitrageOpportunity,
                  buy_ex: BaseExchange, sell_ex: BaseExchange,
                  amount_usdt: float,
                  dry_run: bool = False) -> ExecutionResult:
    now = datetime.now(timezone.utc)

    if dry_run:
        # Simulate fills at opportunity prices (slippage already applied by caller if backtest)
        base_amount_buy  = amount_usdt / opportunity.buy_price
        base_amount_sell = amount_usdt / opportunity.sell_price  # separate denominator
        buy_result = OrderResult(
            success=True, exchange=buy_ex.name, pair=opportunity.pair, side="buy",
            filled_price=opportunity.buy_price, filled_amount=base_amount_buy)
        sell_result = OrderResult(
            success=True, exchange=sell_ex.name, pair=opportunity.pair, side="sell",
            filled_price=opportunity.sell_price, filled_amount=base_amount_sell)
    else:
        buy_task  = buy_ex.place_market_order(opportunity.pair, "buy",  amount_usdt)
        sell_task = sell_ex.place_market_order(opportunity.pair, "sell", amount_usdt)
        raw = await asyncio.gather(buy_task, sell_task, return_exceptions=True)

        def _to_result(r, side: str, ex: BaseExchange) -> OrderResult:
            if isinstance(r, Exception):
                return OrderResult(success=False, exchange=ex.name, pair=opportunity.pair,
                                   side=side, filled_price=0.0, filled_amount=0.0,
                                   error_msg=str(r))
            return r

        buy_result  = _to_result(raw[0], "buy",  buy_ex)
        sell_result = _to_result(raw[1], "sell", sell_ex)

    success = buy_result.success and sell_result.success
    pnl = 0.0
    if success:
        matched_amount = min(buy_result.filled_amount, sell_result.filled_amount)
        gross = (sell_result.filled_price - buy_result.filled_price) * matched_amount
        fees  = (buy_ex.taker_fee() + sell_ex.taker_fee()) * amount_usdt
        pnl   = gross - fees

    return ExecutionResult(
        opportunity=opportunity, buy_result=buy_result, sell_result=sell_result,
        amount_usdt=amount_usdt, simulated=dry_run, executed_at=now,
        realized_pnl_usdt=pnl, success=success)
```

`realized_pnl_usdt` is computed for both real and dry_run successful trades (useful for paper trading P&L tracking). It is `0.0` only when either leg failed.

### `monitor.py`

Async entry point: `asyncio.run(monitor.start(crypto_cfg, dry_run))`.
Receives `crypto_cfg` — the dict loaded from `crypto_settings.yaml`, not the main `settings.yaml`.

**Balance caching:**
- Fetch all exchange USDT balances on startup via `get_balance("USDT")`
- Refresh every `monitor.balance_refresh_seconds` (config, default 30) via background `asyncio.Task`
- After each successful `ExecutionResult`: immediately update the buy exchange's cached balance by subtracting `amount_usdt` (optimistic update, corrected at next full refresh)
- This prevents over-trading within a 30-second window

**Main loop:**
1. Initialise adapters: `BinanceExchange(crypto_cfg["exchanges"]["binance"])`, etc.
2. Create `queue: asyncio.Queue[ArbitrageOpportunity]`; construct `Scanner(exchanges, queue, crypto_cfg)`
3. Start balance refresh background task
4. Start `scanner.run()` as a background `asyncio.Task`
5. Loop: `opp = await queue.get()`
   a. Look up cached USDT balance for buy exchange
   b. `amount_usdt = position_sizer.calculate_amount(balance, crypto_cfg)`
   c. If `amount_usdt > 0`: `result = await executor.execute(opp, ..., amount_usdt, dry_run)`
   d. Append `result` to `reports/arb_log.csv` (pandas, `mode='a'`, `header=not file_exists`)
   e. `scanner.set_cooldown(opp.pair, opp.buy_exchange, opp.sell_exchange)`
   f. Optimistically subtract `amount_usdt` from cached buy-exchange balance
6. On Ctrl-C (`asyncio.CancelledError`): await `ex.close()` for all adapters, then exit

**Rich console:** Refreshes every second — live opportunity table, cumulative P&L, per-exchange balance.

### `arb_log.csv` schema

Written with `pandas.DataFrame.to_csv(mode='a', header=not file_exists)`. One row per `ExecutionResult`.

| Column | Type | Notes |
|--------|------|-------|
| `executed_at` | ISO datetime UTC | |
| `pair` | str | e.g. `BTC/USDT` |
| `buy_exchange` | str | |
| `sell_exchange` | str | |
| `buy_price` | float | ask at detection time |
| `sell_price` | float | bid at detection time |
| `spread_pct` | float | net spread after fees |
| `amount_usdt` | float | requested trade size |
| `buy_filled_price` | float | 0.0 on failure |
| `buy_filled_amount` | float | base currency, 0.0 on failure |
| `sell_filled_price` | float | 0.0 on failure |
| `sell_filled_amount` | float | base currency, 0.0 on failure |
| `realized_pnl_usdt` | float | 0.0 if either leg failed |
| `success` | bool | both legs filled |
| `simulated` | bool | dry_run mode |
| `buy_error` | str | empty if success |
| `sell_error` | str | empty if success |

### `backtest/downloader.py`

**Binance (primary):** L2 orderbook depth snapshots from `data.binance.vision`.
- Actual wide-CSV format per row: `lastUpdateId, timestamp, asks[0].price, asks[0].qty, asks[1].price, asks[1].qty, …, bids[0].price, bids[0].qty, …`
- URL: `https://data.binance.vision/data/spot/daily/depth/<BTCUSDT>/<BTCUSDT>-bookDepth-<YYYY-MM-DD>.zip`
- Only level-0 (top-of-book) ask and bid are extracted and stored
- Stored as `cache/crypto/binance/<BTCUSDT>/<YYYY-MM-DD>.parquet` with columns `[timestamp_ms, best_ask, best_bid]`

**Other exchanges:** Trade tick data used as proxy. Synthetic bid/ask:
```
synthetic_ask = last_price * 1.0002
synthetic_bid = last_price * 0.9998
```
Backtest reports display a disclaimer when tick-proxy data is used.

**`pair_normalized` format:** canonical pair with `/` replaced by `_`, uppercase. e.g. `BTC/USDT` → `BTC_USDT`.
Stored as `cache/crypto/<exchange>/BTC_USDT/<YYYY-MM-DD>.parquet`

**`pair=None` behaviour:** if `--pair` is omitted, `download()` downloads all common pairs (intersection of enabled exchanges). `run_backtest()` with `pair=None` also runs all common pairs sequentially.

CLI: `python main.py arb --download-data --pair BTC/USDT --days 90`

### `backtest/replayer.py`

Replays downloaded data to simulate arbitrage. The replayer uses historical `timestamp_ms` values to populate `ArbitrageOpportunity.detected_at` (not wall-clock time).

1. Load parquet data for both exchanges for the date range
2. For non-Binance: apply synthetic bid/ask from tick `last_price`
3. Merge all updates into single time-sorted event stream (key: `timestamp_ms`)
4. Maintain `(ask, bid, updated_at)` state per exchange; apply same staleness check
5. On each event: `calculate_spread()` for both directions
6. If spread ≥ threshold and not on cooldown:
   - Apply slippage **before** constructing `ArbitrageOpportunity`:
     ```python
     adj_buy_price  = ask  * (1 + slippage_pct)
     adj_sell_price = bid  * (1 - slippage_pct)
     ```
   - Create `ArbitrageOpportunity` with `buy_price=adj_buy_price`, `sell_price=adj_sell_price`, `detected_at=datetime.fromtimestamp(ts_ms/1000, tz=timezone.utc)`
   - Call `executor.execute(opp, ..., amount_usdt, dry_run=True)`
   - The executor's dry_run path uses these already-adjusted prices, so slippage is correctly included in P&L

### `backtest/arb_report.py`

`generate_report(log_path: str) -> str` — reads `arb_log.csv`, generates HTML, returns output path.
(Named `generate_report`, not `print_report` — it writes a file, not stdout.)

Called from `cmd_arb` as: `path = generate_report("reports/arb_log.csv"); console.print(path)`

**Statistics:**
- Total P&L (USDT), total return %
- Win rate (success=True and pnl > 0)
- Max drawdown (cumulative P&L curve)
- Sharpe ratio (daily P&L series)
- Opportunities detected vs executed (fill rate)
- Best and worst pairs by total P&L
- Hourly opportunity count heatmap
- Disclaimer if `simulated=True` rows present or tick-proxy data used

---

## Configuration (`config/crypto_settings.yaml`)

API keys are **not** stored here — use `.env` file (loaded by existing `python-dotenv` in `main.py`).

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
  min_spread_pct: 0.005
  cooldown_seconds: 30
  price_staleness_seconds: 5

position:
  max_usdt: 1000
  min_balance_pct: 0.05
  min_usdt: 20

monitor:
  balance_refresh_seconds: 30

backtest:
  slippage_pct: 0.0005
```

---

## CLI Integration (`main.py`)

`cmd_arb` loads `crypto_settings.yaml` independently — it does **not** use the main `settings.yaml` config. All positional config reads in `crypto/` components use this crypto-specific dict.

`--run`, `--dry-run`, `--backtest`, `--download-data`, and `--report` are all mutually exclusive. argparse `add_mutually_exclusive_group` enforces this at parse time.

Note: argparse converts hyphenated flags to underscored attributes (`--dry-run` → `args.dry_run`, `--download-data` → `args.download_data`).

```python
def load_crypto_config(path: str = "config/crypto_settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)

def cmd_arb(args, _main_cfg):  # _main_cfg unused, crypto has its own config
    import asyncio
    crypto_cfg = load_crypto_config()

    if args.run or args.dry_run:
        from crypto.monitor import start as arb_start
        asyncio.run(arb_start(crypto_cfg, dry_run=args.dry_run))
    elif args.backtest:
        from crypto.backtest.replayer import run_backtest
        asyncio.run(run_backtest(crypto_cfg, pair=args.pair,
                                 start=args.start, end=args.end))
    elif args.download_data:
        from crypto.backtest.downloader import download
        asyncio.run(download(pair=args.pair, days=args.days))
    elif args.report:
        from crypto.backtest.arb_report import generate_report
        path = generate_report("reports/arb_log.csv")
        console.print(f"報告：{path}")

# In main():
arb = sub.add_parser("arb", help="加密貨幣跨所套利（搬磚）")
mode = arb.add_mutually_exclusive_group()
mode.add_argument("--run",           action="store_true", help="全自動真實下單")
mode.add_argument("--dry-run",       action="store_true", help="即時 Paper Trading（不下單）")
mode.add_argument("--backtest",      action="store_true", help="歷史回測")
mode.add_argument("--download-data", action="store_true", help="下載歷史 L2 資料")
mode.add_argument("--report",        action="store_true", help="顯示歷史套利紀錄")
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
# python-dotenv already present
```

---

## Data Flow Summary

```
Real / Paper mode:
  crypto_settings.yaml + .env → exchange adapters (constructor receives cfg section)
  WebSocket feeds → scanner.py (prices dict, staleness-checked)
  → arbitrage.py (calculate_spread, both directions, cooldown)
  → monitor.py: position_sizer(cached_balance, crypto_cfg) → amount_usdt
  → executor.execute(opportunity, amount_usdt, dry_run)
  → ExecutionResult → arb_log.csv (pandas append) + Rich console

Backtest mode:
  downloader.py → cache/crypto/<exchange>/<pair>/<date>.parquet
  → replayer.py (time-sorted events, synthetic bid/ask, slippage applied before ArbitrageOpportunity)
  → executor.execute(..., dry_run=True) → simulated ExecutionResult list
  → arb_report.py → reports/backtest_arb_<pair>_<date>.html
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| WebSocket disconnect | Exponential backoff 1s→2s→…60s, max 5 retries |
| 5 retries exhausted | `close()` adapter, remove from active set, system continues |
| Price staleness > threshold | Skip pair until fresh update |
| Single leg order failure | `OrderResult(success=False, filled_price=0.0, filled_amount=0.0, error_msg=...)` |
| Both legs fail | Log ExecutionResult, continue |
| balance < min_usdt | `position_sizer` returns 0.0, skip trade, log warning |
| Exchange API rate limit | Log warning, back off |
| Missing L2 data for date | Skip that date in backtest, warn user |
| Tick data used as proxy | Warn per pair, add disclaimer to HTML report |

---

## Out of Scope

- On-chain fund transfer / rebalancing between exchanges (future sub-project)
- Triangular arbitrage (A→B→C within one exchange)
- Futures/perpetual arbitrage (basis trading)
- CEX/DEX arbitrage
