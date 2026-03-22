# backtest/report.py
import csv
from pathlib import Path
from datetime import datetime


class BacktestReport:
    def __init__(self, reports_dir: str = "reports/"):
        self._dir = Path(reports_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, ticker: str, stats: dict) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"backtest_{ticker}_{ts}"

        # CSV trade log
        csv_path = self._dir / f"{stem}.csv"
        trades = stats.get("trades", [])
        if trades:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=trades[0].keys())
                writer.writeheader()
                writer.writerows(trades)

        # HTML report
        html_path = self._dir / f"{stem}.html"
        rows = "".join(
            f"<tr><td>{t['reason']}</td><td>{t['entry_price']:.2f}</td>"
            f"<td>{t['exit_price']:.2f}</td><td>{t['pnl_pct']*100:.2f}%</td></tr>"
            for t in trades
        )
        html = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>回測報告 {ticker}</title>
<style>body{{font-family:sans-serif;padding:20px}}
table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;text-align:right}}
th{{background:#f2f2f2}}</style></head><body>
<h1>回測報告：{ticker}</h1>
<table><tr><th>指標</th><th>數值</th></tr>
<tr><td>總報酬率</td><td>{stats['total_return']*100:.2f}%</td></tr>
<tr><td>最大回撤</td><td>{stats['max_drawdown']*100:.2f}%</td></tr>
<tr><td>夏普比率</td><td>{stats['sharpe_ratio']:.4f}</td></tr>
<tr><td>勝率</td><td>{stats['win_rate']*100:.1f}%</td></tr>
<tr><td>交易次數</td><td>{stats['trade_count']}</td></tr>
</table>
<h2>交易明細</h2>
<table><tr><th>出場原因</th><th>買入價</th><th>賣出價</th><th>損益</th></tr>
{rows}</table></body></html>"""
        html_path.write_text(html, encoding="utf-8")
        return str(html_path)
