from __future__ import annotations

import asyncio

from rich.console import Console

from crypto.config import enabled_exchange_names
from crypto.exchanges.simulated import SimulatedExchange
from crypto.scanner import Scanner

console = Console()


def _build_simulated_adapters(cfg: dict):
    exchanges_cfg = cfg.get("exchanges", {})
    adapters = {}

    sample_quotes = {
        "binance": {"BTC/USDT": (50000.0, 50010.0)},
        "max_exchange": {"BTC/USDT": (50020.0, 50350.0)},
        "okx": {"BTC/USDT": (50015.0, 50025.0)},
        "bybit": {"BTC/USDT": (50012.0, 50022.0)},
        "bitopro": {"BTC/USDT": (50030.0, 50040.0)},
    }

    for name in enabled_exchange_names(cfg):
        ex_cfg = exchanges_cfg.get(name, {})
        adapters[name] = SimulatedExchange(
            name,
            sample_quotes.get(name, {"BTC/USDT": (50000.0, 50005.0)}),
            taker_fee_override=ex_cfg.get("taker_fee_override"),
        )
    return adapters


async def start(cfg: dict, dry_run: bool = False) -> None:
    enabled = enabled_exchange_names(cfg)
    if len(enabled) < 2:
        raise ValueError("need at least 2 enabled exchanges")

    mode = "DRY-RUN" if dry_run else "LIVE"
    console.print(f"[cyan]Crypto arbitrage monitor bootstrap ({mode})[/cyan]")
    console.print(f"Enabled exchanges: {', '.join(enabled)}")

    adapters = _build_simulated_adapters(cfg)
    queue: asyncio.Queue = asyncio.Queue()
    scanner = Scanner(adapters, queue, cfg)
    await scanner.run()

    if queue.empty():
        console.print("[yellow]No arbitrage opportunity detected in bootstrap run.[/yellow]")
        return

    opp = await queue.get()
    console.print(
        f"[green]Opportunity:[/green] {opp.pair} | buy={opp.buy_exchange} @ {opp.buy_price} "
        f"→ sell={opp.sell_exchange} @ {opp.sell_price} | spread={opp.spread_pct:.4%}"
    )
