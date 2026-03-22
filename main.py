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
    from data.bulk_download import load_chips_from_cache
    from backtest.engine import BacktestEngine
    from backtest.report import BacktestReport
    from signals.chips import ChipsSignals

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

        # Load chips from bulk cache if available
        chips_cache = load_chips_from_cache(ticker)

        stats = engine.run(df, ticker=ticker, chips_cache=chips_cache)
        path = reporter.save(ticker, stats)
        chips_note = " [有籌碼]" if chips_cache else " [無籌碼]"
        console.print(f"[cyan]{ticker}[/cyan]{chips_note} 報酬率: [bold]{stats['total_return']*100:.2f}%[/bold] "
                      f"勝率: {stats['win_rate']*100:.1f}% 報告: {path}")


_paper_broker = None


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


def cmd_download(args, cfg):
    from data.stock_list import get_all_stock_ids
    from data.bulk_download import (
        download_all_prices, download_chips_batch,
        download_status, _load_progress
    )
    from data.cache import Cache

    token = os.getenv("FINMIND_TOKEN", "")
    cache = Cache(cache_dir=cfg["data"]["cache_dir"])
    max_req = cfg["data"]["max_api_requests_per_day"]

    console.print("[bold cyan]取得全台上市股票清單...[/bold cyan]")
    stock_ids = get_all_stock_ids(finmind_token=token)
    console.print(f"共 {len(stock_ids)} 支股票")

    if args.status:
        download_status(stock_ids)
        return

    if args.reset:
        from pathlib import Path
        p = Path("cache/download_progress.json")
        if p.exists():
            p.unlink()
        console.print("[yellow]進度已重設[/yellow]")

    if not args.chips_only:
        download_all_prices(stock_ids, cache, force=args.reset)

    if not args.price_only:
        if not token:
            console.print("[yellow]警告：未設定 FINMIND_TOKEN，跳過籌碼下載[/yellow]")
        else:
            download_chips_batch(
                stock_ids, finmind_token=token,
                max_requests=max_req, force=args.reset
            )

    download_status(stock_ids)


def cmd_positions(args, cfg):
    broker = _get_paper_broker(cfg)
    positions = broker.get_positions()
    if not positions:
        console.print("[yellow]目前無持倉[/yellow]")
        return
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

    dl = sub.add_parser("download", help="批次下載全台股歷史資料")
    dl.add_argument("--price-only", action="store_true", help="只下載價格資料")
    dl.add_argument("--chips-only", action="store_true", help="只下載籌碼資料")
    dl.add_argument("--reset", action="store_true", help="重設進度，重新下載")
    dl.add_argument("--status", action="store_true", help="顯示下載進度")

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
    elif args.command == "download":
        cmd_download(args, cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
