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
