# crypto/monitor.py
"""
Main event loop for real-time arbitrage monitoring.
Usage: asyncio.run(start(crypto_cfg, dry_run=True))
"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.live import Live
from rich.table import Table

from crypto.arbitrage import ArbitrageOpportunity
from crypto.exchanges.base import ExecutionResult
from crypto.scanner import Scanner
from crypto import position_sizer
from crypto import executor

logger = logging.getLogger(__name__)
console = Console()


def _build_adapters(crypto_cfg: dict) -> dict:
    """Initialise all enabled exchange adapters."""
    from crypto.exchanges.binance      import BinanceExchange
    from crypto.exchanges.okx          import OKXExchange
    from crypto.exchanges.bybit        import BybitExchange
    from crypto.exchanges.max_exchange import MAXExchange
    from crypto.exchanges.bitopro      import BitoproExchange

    factories = {
        "binance":    BinanceExchange,
        "okx":        OKXExchange,
        "bybit":      BybitExchange,
        "max_exchange": MAXExchange,
        "bitopro":    BitoproExchange,
    }
    exchanges = {}
    for name, cls in factories.items():
        cfg_section = crypto_cfg["exchanges"].get(name, {})
        if cfg_section.get("enabled", False):
            ex = cls(cfg_section)
            exchanges[ex.name] = ex
    return exchanges


def _append_to_csv(result: ExecutionResult, path: str) -> None:
    """Append one ExecutionResult row to arb_log.csv."""
    opp = result.opportunity
    row = {
        "executed_at":        result.executed_at.isoformat(),
        "pair":               opp.pair,
        "buy_exchange":       opp.buy_exchange,
        "sell_exchange":      opp.sell_exchange,
        "buy_price":          opp.buy_price,
        "sell_price":         opp.sell_price,
        "spread_pct":         opp.spread_pct,
        "amount_usdt":        result.amount_usdt,
        "buy_filled_price":   result.buy_result.filled_price,
        "buy_filled_amount":  result.buy_result.filled_amount,
        "sell_filled_price":  result.sell_result.filled_price,
        "sell_filled_amount": result.sell_result.filled_amount,
        "realized_pnl_usdt":  result.realized_pnl_usdt,
        "success":            result.success,
        "simulated":          result.simulated,
        "buy_error":          result.buy_result.error_msg,
        "sell_error":         result.sell_result.error_msg,
    }
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([row]).to_csv(
        path, mode="a", header=not log_path.exists(), index=False
    )


def _make_display_table(balances: dict, cumulative_pnl: float,
                        recent_opps: list) -> Table:
    table = Table(title="Crypto Arbitrage Monitor")
    table.add_column("Exchange")
    table.add_column("USDT Balance", justify="right")
    for name, bal in balances.items():
        table.add_row(name, f"{bal:,.2f}")
    table.add_section()
    table.add_row("Cumulative P&L", f"{cumulative_pnl:+.4f} USDT")
    return table


async def _refresh_balances(exchanges: dict, balances: dict, cfg: dict) -> None:
    interval = cfg.get("monitor", {}).get("balance_refresh_seconds", 30)
    while True:
        await asyncio.sleep(interval)
        for name, ex in list(exchanges.items()):
            try:
                balances[name] = await ex.get_balance("USDT")
            except Exception as e:
                logger.warning(f"Balance refresh failed for {name}: {e}")


async def _live_display(balances: dict, pnl_ref: list, live: Live) -> None:
    """Update Rich live display every second. pnl_ref is a mutable list[float]."""
    while True:
        await asyncio.sleep(1)
        table = _make_display_table(balances, pnl_ref[0], [])
        live.update(table)


async def start(crypto_cfg: dict, dry_run: bool = False) -> None:
    """
    Main entry point for live/paper arbitrage monitoring.
    Called via: asyncio.run(start(crypto_cfg, dry_run=True))
    """
    mode = "Paper Trading (dry-run)" if dry_run else "LIVE TRADING"
    console.print(f"[bold cyan]Crypto Arbitrage — {mode}[/bold cyan]")

    exchanges = _build_adapters(crypto_cfg)
    if len(exchanges) < 2:
        raise ValueError("need at least 2 enabled exchanges")

    # Initial balance fetch
    balances: dict[str, float] = {}
    for name, ex in exchanges.items():
        try:
            balances[name] = await ex.get_balance("USDT")
        except Exception:
            balances[name] = 0.0

    queue: asyncio.Queue = asyncio.Queue()
    scanner = Scanner(exchanges, queue, crypto_cfg)
    pnl_ref = [0.0]  # mutable container for cumulative P&L

    with Live(console=console, refresh_per_second=1) as live:
        scanner_task = asyncio.create_task(scanner.run())
        refresh_task = asyncio.create_task(_refresh_balances(exchanges, balances, crypto_cfg))
        display_task = asyncio.create_task(_live_display(balances, pnl_ref, live))

        try:
            while True:
                opp = await queue.get()
                if (opp.buy_exchange not in exchanges or
                        opp.sell_exchange not in exchanges):
                    continue

                amount_usdt = position_sizer.calculate_amount(
                    balances.get(opp.buy_exchange, 0.0), crypto_cfg
                )
                if amount_usdt == 0.0:
                    continue

                result = await executor.execute(
                    opp,
                    exchanges[opp.buy_exchange],
                    exchanges[opp.sell_exchange],
                    amount_usdt,
                    dry_run,
                )
                _append_to_csv(result, "reports/arb_log.csv")
                scanner.set_cooldown(opp.pair, opp.buy_exchange, opp.sell_exchange)
                balances[opp.buy_exchange] = max(
                    0.0, balances[opp.buy_exchange] - amount_usdt
                )
                if result.success:
                    pnl_ref[0] += result.realized_pnl_usdt

                status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
                console.log(
                    f"{status} {opp.pair} {opp.buy_exchange}→{opp.sell_exchange} "
                    f"spread={opp.spread_pct:.3%} pnl={result.realized_pnl_usdt:+.4f} USDT"
                )

        except asyncio.CancelledError:
            for task in [scanner_task, refresh_task, display_task]:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            for ex in exchanges.values():
                await ex.close()
