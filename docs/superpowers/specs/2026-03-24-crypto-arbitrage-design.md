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
Each adapter's `get_tradable_pairs()` returns pairs in this canonical format. Adapters handle internal symbol conversion (e.g. Binance `BTCUSDT` → `BTC/USDT`, OKX `BTC-USDT` → `BTC/USDT`) inside the adapter, never exposing exchange-native symbols outside.

**Callback signature for `subscribe_orderbook`:**
```python
OrderbookCallback = Callable[[str, str, float, float], None]
# args: (exchange_name: str, pair: str, best_ask: float, best_bid: float)
```
Each adapter calls this callback on every orderbook update with the current best ask and best bid.

**Abstract interface:**
```python
class BaseExchange(ABC):
    name: str  # lowercase identifier, e.g. "binance", "max"

    async def get_tradable_pairs(self) -> list[str]
    # Returns canonical pairs (BASE/QUOTE) available on this exchange

    async def subscribe_orderbook(self, pairs: list[str],
                                  callback: OrderbookCallback) -> None
    # Opens WebSocket, calls callback on each best bid/ask update

    async def get_balance(self, asset: str) -> float
    # Returns available balance for asset (e.g. "USDT", "BTC")

    async def place_market_order(self, pair: str, side: str,
                                 amount_usdt: float) -> OrderResult
    # side: "buy" or "sell"; amount_usdt is the quote currency amount

    def taker_fee(self) -> float   # e.g. 0.001 for 0.1%
    def withdraw_fee(self, asset: str) -> float  # reserved for future use
```

**Shared dataclasses (defined in `base.py`, imported everywhere):**

```python
@dataclass
class OrderResult:
    success: bool
    exchange: str
    pair: str
    side: str          # "buy" or "sell"
    filled_price: float
    filled_amount: float
    error_msg: str = ""

@dataclass
class ExecutionResult:
    opportunity: "ArbitrageOpportunity"
    buy_result: OrderResult
    sell_result: OrderResult
    simulated: bool           # True if dry_run mode
    executed_at: datetime
    realized_pnl_usdt: float  # 0.0 if either leg failed or simulated
    success: bool             # True only if both legs filled

    @property
    def failed(self) -> bool:
        return not self.success
```

### `exchanges/*.py` — Individual adapters

Each adapter implements `BaseExchange`. Fee rates are hardcoded defaults; individual overrides are loaded from config.

| Exchange  | Taker Fee | SDK / Library         |
|-----------|-----------|-----------------------|
| Binance   | 0.10%     | `python-binance`      |
| OKX       | 0.10%     | `python-okx`          |
| Bybit     | 0.10%     | `pybit`               |
| MAX       | 0.15%     | `websockets` + REST   |
| BitoPro   | 0.20%     | `websockets` + REST   |

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
- After 5 failed retries: log error, mark exchange as unavailable, continue running on remaining exchanges
- `monitor.py` continues operating with remaining enabled exchanges; it does not halt

### `arbitrage.py`

```python
@dataclass
class ArbitrageOpportunity:
    pair: str              # canonical format, e.g. "BTC/USDT"
    buy_exchange: str      # exchange name where we buy (cheaper ask)
    sell_exchange: str     # exchange name where we sell (higher bid)
    buy_price: float       # best ask on buy exchange
    sell_price: float      # best bid on sell exchange
    spread_pct: float      # net spread after both taker fees
    amount_usdt: float     # calculated trade size (filled by position_sizer)
    detected_at: datetime

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
4. Maintain in-memory dict: `prices[exchange_name][pair] = (best_ask, best_bid)`

**On each callback invocation:**
1. Update `prices[exchange_name][pair]`
2. For each pair where ≥ 2 exchanges have current prices: evaluate both directions
3. If spread ≥ `min_spread_pct`: check cooldown for `(pair, buy_exchange, sell_exchange)` triplet
4. If not on cooldown: emit `ArbitrageOpportunity` to `monitor.py`

**Cooldown** is keyed on `(pair, buy_exchange, sell_exchange)` triplet. BTC/USDT Binance→MAX and BTC/USDT MAX→Binance are independent cooldowns.

### `position_sizer.py`

```python
def calculate_amount(balance_usdt: float, cfg: dict) -> float:
    """
    Returns trade amount in USDT.
    Returns 0.0 if balance is below the absolute minimum floor.

    Dual constraint:
    - Never exceed max_usdt
    - Never use less than min_balance_pct of balance
    - Never trade if balance < min_usdt (absolute floor)
    """
    max_usdt = cfg["position"]["max_usdt"]           # e.g. 1000
    min_balance_pct = cfg["position"]["min_balance_pct"]  # e.g. 0.05
    min_usdt = cfg["position"]["min_usdt"]           # e.g. 20 (absolute floor)

    if balance_usdt < min_usdt:
        return 0.0  # skip: balance too low to trade meaningfully

    min_from_pct = balance_usdt * min_balance_pct    # e.g. $5000 * 5% = $250
    amount = min(max_usdt, balance_usdt)             # cap at max_usdt
    amount = max(amount, min_from_pct)               # ensure at least min_from_pct
    return amount
```

Config keys:
- `max_usdt`: hard upper bound per trade (e.g. 1000)
- `min_balance_pct`: lower bound as fraction of balance (e.g. 0.05)
- `min_usdt`: absolute minimum floor below which we skip (e.g. 20)

### `executor.py`

```python
async def execute(opportunity: ArbitrageOpportunity,
                  buy_ex: BaseExchange,
                  sell_ex: BaseExchange,
                  dry_run: bool = False) -> ExecutionResult:
    if dry_run:
        # Simulate fill at current prices, no real orders
        buy_result  = OrderResult(success=True, exchange=buy_ex.name,
                                  pair=opportunity.pair, side="buy",
                                  filled_price=opportunity.buy_price,
                                  filled_amount=opportunity.amount_usdt / opportunity.buy_price)
        sell_result = OrderResult(success=True, exchange=sell_ex.name,
                                  pair=opportunity.pair, side="sell",
                                  filled_price=opportunity.sell_price,
                                  filled_amount=opportunity.amount_usdt / opportunity.buy_price)
    else:
        buy_task  = buy_ex.place_market_order(opportunity.pair, "buy",  opportunity.amount_usdt)
        sell_task = sell_ex.place_market_order(opportunity.pair, "sell", opportunity.amount_usdt)
        buy_result, sell_result = await asyncio.gather(buy_task, sell_task,
                                                       return_exceptions=True)
        # Exceptions from gather() are returned as values, not raised
        if isinstance(buy_result, Exception):
            buy_result = OrderResult(success=False, ..., error_msg=str(buy_result))
        if isinstance(sell_result, Exception):
            sell_result = OrderResult(success=False, ..., error_msg=str(sell_result))

    success = buy_result.success and sell_result.success
    pnl = 0.0
    if success:
        pnl = (sell_result.filled_price - buy_result.filled_price) * buy_result.filled_amount \
              - buy_ex.taker_fee() * opportunity.amount_usdt \
              - sell_ex.taker_fee() * opportunity.amount_usdt

    return ExecutionResult(
        opportunity=opportunity,
        buy_result=buy_result,
        sell_result=sell_result,
        simulated=dry_run,
        executed_at=datetime.utcnow(),
        realized_pnl_usdt=pnl,
        success=success,
    )
```

Single-leg failures: logged, no hedge, continue monitoring.

### `monitor.py`

Main async event loop started from `main.py` via `asyncio.run(monitor.start(cfg, dry_run))`.

**Responsibilities:**
1. Initialise all enabled exchange adapters (load API keys from env)
2. Start `scanner.py` WebSocket subscriptions
3. On each `ArbitrageOpportunity`:
   a. Call `position_sizer.calculate_amount(buy_exchange_balance, cfg)`
   b. If amount > 0: call `executor.execute(opportunity, ..., dry_run=dry_run)`
   c. Append `ExecutionResult` to `reports/arb_log.csv`
4. Refresh Rich console table every second (opportunities, cumulative P&L, balances)

### `arb_log.csv` schema

One row per `ExecutionResult`:

| Column | Type | Description |
|--------|------|-------------|
| `executed_at` | ISO datetime | UTC timestamp |
| `pair` | str | e.g. `BTC/USDT` |
| `buy_exchange` | str | |
| `sell_exchange` | str | |
| `buy_price` | float | |
| `sell_price` | float | |
| `spread_pct` | float | net spread after fees |
| `amount_usdt` | float | trade size |
| `realized_pnl_usdt` | float | 0 if failed or simulated |
| `success` | bool | both legs filled |
| `simulated` | bool | dry_run mode |
| `buy_error` | str | empty if success |
| `sell_error` | str | empty if success |

### `backtest/downloader.py`

Downloads and caches historical data for backtesting.

**Binance (primary exchange):** L2 orderbook depth snapshots from `data.binance.vision`.
- Daily `.csv.gz` files, format: `timestamp, side, price, quantity` for top-N levels
- Stored as `cache/crypto/binance/<BTCUSDT>/<YYYY-MM-DD>.parquet`

**Other exchanges (opposing leg):** Since only Binance provides free L2 history, other exchanges use **trade tick data** (last traded price) as a proxy. The replayer converts tick data to a synthetic best bid/ask using the last trade price ± 0.02% half-spread estimate. This introduces minor inaccuracy but is clearly documented in backtest reports.

Stored as `cache/crypto/<exchange>/<pair_normalized>/<YYYY-MM-DD>.parquet`

CLI: `python main.py arb --download-data --pair BTC/USDT --days 90`

### `backtest/replayer.py`

Replays downloaded data chronologically to simulate arbitrage:

1. Load data for both exchanges for the date range
2. For non-Binance exchanges: convert tick `last_price` → synthetic `(ask, bid)` = `(last * 1.0002, last * 0.9998)`
3. Merge all updates into a single time-sorted event stream
4. Maintain current `(ask, bid)` state per exchange per pair
5. On each event: call `calculate_spread()` for both directions
6. If spread ≥ threshold and not on cooldown: create simulated `ExecutionResult`
   - Fill price = recorded orderbook price + `slippage_pct`
7. Collect all `ExecutionResult` objects → pass to `arb_report.py`

### `backtest/arb_report.py`

Generates HTML report (same visual style as `backtest/report.py`, different schema):

**Statistics:**
- Total P&L (USDT), total return %
- Win rate (both legs filled and profitable)
- Max drawdown
- Sharpe ratio (daily P&L series)
- Opportunities detected vs executed (fill rate)
- Best and worst pairs by P&L
- Hourly opportunity count heatmap

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

position:
  max_usdt: 1000             # hard upper limit per trade
  min_balance_pct: 0.05      # lower bound: 5% of available balance
  min_usdt: 20               # absolute floor: skip if balance < this

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

`asyncio.run()` is called inside `cmd_arb()`, keeping `main()` synchronous:

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
arb.add_argument("--run",           action="store_true", help="全自動真實下單")
arb.add_argument("--dry-run",       action="store_true", help="即時 Paper Trading（不下單）")
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
```

MAX and BitoPro use `websockets` (already listed) + standard `aiohttp` for REST.

---

## Data Flow Summary

```
Real / Paper mode:
  .env API keys → exchange adapters
  WebSocket feeds → scanner.py (prices dict)
  → arbitrage.py (calculate_spread, both directions)
  → position_sizer.py (amount)
  → executor.py (real orders OR dry_run simulation)
  → ExecutionResult → arb_log.csv + Rich console

Backtest mode:
  downloader.py → cache/crypto/<exchange>/<pair>/<date>.parquet
  → replayer.py (time-sorted event stream, synthetic bid/ask for tick data)
  → arbitrage.py + position_sizer.py
  → simulated ExecutionResult list
  → arb_report.py → reports/backtest_arb_<pair>_<date>.html
```

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| WebSocket disconnect | Exponential backoff 1s→2s→4s…60s, max 5 retries; then mark exchange unavailable, continue on others |
| 5 retries exhausted | Log error, remove exchange from active set; system continues |
| Single leg order failure | Log failure, do NOT hedge, continue monitoring |
| Both legs fail | Log, continue |
| balance < min_usdt | Skip trade, log warning |
| Exchange API rate limit | Back off, log warning |
| Missing L2 data for date | Skip that date in backtest, warn user |
| Tick data used as proxy | Log warning per pair indicating reduced backtest accuracy |

---

## Out of Scope

- On-chain fund transfer / rebalancing between exchanges (future sub-project)
- Triangular arbitrage (A→B→C within one exchange)
- Futures/perpetual arbitrage (basis trading)
- CEX/DEX arbitrage
