# data/bulk_download.py
"""
Resumable bulk downloader for Taiwan stock data.

Price data  : yfinance (no quota limit) — downloads all stocks at once
Chips data  : FinMind  (600 req/day free) — downloads in daily batches
Progress    : cache/download_progress.json (resume across days)

Usage:
    python main.py download [--price-only] [--chips-only] [--reset]
"""
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from data.cache import Cache
from data.stock_list import get_all_stock_ids

logger = logging.getLogger(__name__)
console = Console()

PROGRESS_FILE = Path("cache/download_progress.json")
COMMISSION = 0.001425
YEARS = 5


def _load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"price_done": [], "chips_done": [], "chips_failed": []}


def _save_progress(progress: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def _start_date() -> str:
    return (date.today() - timedelta(days=365 * YEARS)).strftime("%Y-%m-%d")


# ─── Price Download ──────────────────────────────────────────────────────────

def download_all_prices(
    stock_ids: list[str],
    cache: Cache,
    force: bool = False,
) -> dict:
    """
    Download OHLCV data for all stocks via yfinance.
    Uses batch download for speed. Returns {done: int, skipped: int, failed: list}.
    """
    progress_data = _load_progress()
    done_set = set(progress_data.get("price_done", []))

    to_download = stock_ids if force else [s for s in stock_ids if s not in done_set]

    if not to_download:
        console.print("[green]✓ 所有股票價格資料已是最新[/green]")
        return {"done": 0, "skipped": len(stock_ids), "failed": []}

    console.print(f"[cyan]下載 {len(to_download)} 支股票價格資料（yfinance 批次）...[/cyan]")

    # Build ticker list for yfinance batch download
    tw_tickers = [f"{s}.TW" for s in to_download]
    start = _start_date()

    failed = []
    done_count = 0

    # Download in chunks of 100 to avoid yfinance timeout
    chunk_size = 100
    for chunk_start in range(0, len(tw_tickers), chunk_size):
        chunk = tw_tickers[chunk_start:chunk_start + chunk_size]
        chunk_ids = to_download[chunk_start:chunk_start + chunk_size]

        console.print(f"  批次 {chunk_start//chunk_size + 1}/{(len(tw_tickers)-1)//chunk_size + 1}: {len(chunk)} 支...")

        try:
            df_all = yf.download(
                chunk, start=start, progress=False, auto_adjust=True, group_by="ticker"
            )
        except Exception as e:
            logger.error(f"yfinance batch download error: {e}")
            failed.extend(chunk_ids)
            continue

        for ticker_id, tw_ticker in zip(chunk_ids, chunk):
            try:
                if len(chunk) == 1:
                    df = df_all
                else:
                    # MultiIndex: columns are (field, ticker)
                    if tw_ticker in df_all.columns.get_level_values(1):
                        df = df_all.xs(tw_ticker, axis=1, level=1)
                    else:
                        failed.append(ticker_id)
                        continue

                if df is None or df.empty or "Close" not in df.columns:
                    failed.append(ticker_id)
                    continue

                # Flatten MultiIndex columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)

                df.index = pd.to_datetime(df.index)
                cache.save(ticker_id, df)
                done_set.add(ticker_id)
                done_count += 1

            except Exception as e:
                logger.warning(f"Error saving {ticker_id}: {e}")
                failed.append(ticker_id)

        # Save progress after each chunk
        progress_data["price_done"] = list(done_set)
        _save_progress(progress_data)

    console.print(f"[green]✓ 價格下載完成：{done_count} 成功，{len(failed)} 失敗[/green]")
    if failed:
        console.print(f"[yellow]失敗清單：{failed[:20]}{'...' if len(failed)>20 else ''}[/yellow]")

    return {"done": done_count, "skipped": len(stock_ids) - len(to_download), "failed": failed}


# ─── Chips Download ───────────────────────────────────────────────────────────

def download_chips_batch(
    stock_ids: list[str],
    finmind_token: str,
    max_requests: int = 600,
    chips_cache_dir: str = "cache/chips/",
    force: bool = False,
) -> dict:
    """
    Download chips data (institutional + margin) for as many stocks
    as the daily quota allows. Call this once per day; progress is saved.
    Returns {done: int, skipped: int, remaining: int, failed: list}.
    """
    progress_data = _load_progress()
    done_set = set(progress_data.get("chips_done", []))
    failed_set = set(progress_data.get("chips_failed", []))

    remaining = [s for s in stock_ids if s not in done_set and s not in failed_set]
    if force:
        remaining = stock_ids
        done_set.clear()
        failed_set.clear()

    if not remaining:
        console.print("[green]✓ 所有股票籌碼資料已下載完畢[/green]")
        return {"done": 0, "skipped": len(done_set), "remaining": 0, "failed": list(failed_set)}

    # Budget: each stock costs 2 requests (institutional + margin)
    can_do = min(max_requests // 2, len(remaining))
    batch = remaining[:can_do]

    console.print(f"[cyan]籌碼下載：今日配額 {max_requests} 次，可處理 {can_do} 支，剩餘 {len(remaining)} 支[/cyan]")

    try:
        from finmind.data import DataLoader
        dl = DataLoader()
        dl.login_by_token(api_token=finmind_token)
    except Exception as e:
        console.print(f"[red]FinMind 登入失敗：{e}[/red]")
        return {"done": 0, "skipped": len(done_set), "remaining": len(remaining), "failed": []}

    chips_dir = Path(chips_cache_dir)
    chips_dir.mkdir(parents=True, exist_ok=True)
    start = _start_date()
    done_count = 0
    failed_list = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("下載籌碼資料...", total=len(batch))

        for ticker_id in batch:
            try:
                # Institutional investors
                inst = dl.taiwan_stock_institutional_investors(
                    stock_id=ticker_id, start_date=start
                )
                # Margin purchase
                margin = dl.taiwan_stock_margin_purchase_short_sale(
                    stock_id=ticker_id, start_date=start
                )

                if inst is not None and not inst.empty:
                    inst.to_parquet(chips_dir / f"{ticker_id}_inst.parquet")
                if margin is not None and not margin.empty:
                    margin.to_parquet(chips_dir / f"{ticker_id}_margin.parquet")

                done_set.add(ticker_id)
                done_count += 1

            except Exception as e:
                logger.warning(f"FinMind chips error for {ticker_id}: {e}")
                failed_list.append(ticker_id)
                failed_set.add(ticker_id)

            prog.advance(task)

            # Save progress every 10 stocks
            if done_count % 10 == 0:
                progress_data["chips_done"] = list(done_set)
                progress_data["chips_failed"] = list(failed_set)
                _save_progress(progress_data)

    # Final save
    progress_data["chips_done"] = list(done_set)
    progress_data["chips_failed"] = list(failed_set)
    _save_progress(progress_data)

    remaining_after = len(stock_ids) - len(done_set) - len(failed_set)
    console.print(
        f"[green]✓ 籌碼下載完成：{done_count} 成功，{len(failed_list)} 失敗，"
        f"剩餘 {remaining_after} 支待明日繼續[/green]"
    )

    return {
        "done": done_count,
        "skipped": len(done_set) - done_count,
        "remaining": remaining_after,
        "failed": failed_list,
    }


# ─── Load Chips from Cache ────────────────────────────────────────────────────

def load_chips_from_cache(ticker_id: str, chips_cache_dir: str = "cache/chips/") -> dict | None:
    """Load cached chips data. Returns dict with 'institutional' and 'margin', or None."""
    chips_dir = Path(chips_cache_dir)
    inst_path = chips_dir / f"{ticker_id}_inst.parquet"
    margin_path = chips_dir / f"{ticker_id}_margin.parquet"

    if not inst_path.exists() or not margin_path.exists():
        return None

    try:
        return {
            "institutional": pd.read_parquet(inst_path),
            "margin": pd.read_parquet(margin_path),
        }
    except Exception as e:
        logger.warning(f"Error loading chips cache for {ticker_id}: {e}")
        return None


# ─── Progress Report ──────────────────────────────────────────────────────────

def download_status(stock_ids: list[str]) -> None:
    """Print current download progress."""
    progress_data = _load_progress()
    price_done = len(progress_data.get("price_done", []))
    chips_done = len(progress_data.get("chips_done", []))
    chips_failed = len(progress_data.get("chips_failed", []))
    total = len(stock_ids)

    console.print("\n[bold]下載進度報告[/bold]")
    console.print(f"  總股票數：{total}")
    console.print(f"  價格資料：{price_done}/{total} ({price_done/total*100:.1f}%)")
    console.print(f"  籌碼資料：{chips_done}/{total} ({chips_done/total*100:.1f}%) | 失敗：{chips_failed}")
    chips_remaining = total - chips_done - chips_failed
    if chips_remaining > 0:
        days_left = (chips_remaining * 2 + 599) // 600
        console.print(f"  [yellow]籌碼尚需約 {days_left} 天完成（每天 600 次配額）[/yellow]")
    else:
        console.print(f"  [green]✓ 籌碼資料下載完畢[/green]")
