# backtest/engine.py
import pandas as pd
import numpy as np
from signals.technical import TechnicalSignals
from signals.volume import VolumeSignals
from signals.composite import CompositeScore, SignalStrength
from strategy.entry import EntryFilter
from strategy.exit import ExitSignal

COMMISSION = 0.001425
STT = 0.003
SLIPPAGE = 0.001
DEFAULT_CONFIG = {
    "thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8},
    "position": {"size_pct": 0.10, "max_positions": 8},
    "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
             "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
             "time_stop_days": 20},
}


class BacktestEngine:
    def __init__(self, initial_cash: float = 1_000_000, config: dict = None):
        self._cash = initial_cash
        self._cfg = config or DEFAULT_CONFIG

    def run(self, df: pd.DataFrame, ticker: str) -> dict:
        warmup = 90
        if len(df) < warmup:
            return {"error": "insufficient_data"}

        cash = self._cash
        position_qty = 0
        entry_price = 0.0
        entry_day = 0
        tp1_triggered = False
        trades = []
        equity_history = []

        for i in range(warmup, len(df)):
            window = df.iloc[:i+1]
            close = window["Close"].iloc[-1]

            if position_qty == 0:
                tech = TechnicalSignals(window)
                t_score, _ = tech.score()
                vol = VolumeSignals(window)
                v_score, _ = vol.score()
                cs = CompositeScore(tech_score=t_score, vol_score=v_score, chips_score=None)
                ef = EntryFilter(config=self._cfg)
                if ef.should_enter(cs, window):
                    fill = close * (1 + 0.005 + SLIPPAGE)
                    pos_value = cash * self._cfg["position"]["size_pct"]
                    qty = int(pos_value / fill / 1000) * 1000  # whole lots
                    if qty > 0:
                        cost = fill * qty * (1 + COMMISSION)
                        cash -= cost
                        position_qty = qty
                        entry_price = fill
                        entry_day = i
                        tp1_triggered = False
            else:
                es = ExitSignal(entry_price=entry_price, config=self._cfg)
                es._tp1_triggered = tp1_triggered
                tech = TechnicalSignals(window)
                t_score, _ = tech.score()
                vol = VolumeSignals(window)
                v_score, _ = vol.score()
                cs = CompositeScore(tech_score=t_score, vol_score=v_score, chips_score=None)
                action = es.check(close, i - entry_day, cs.total)
                if action["exit"]:
                    if action["reason"] == "take_profit_1":
                        tp1_triggered = True
                    sell_qty = int(position_qty * action["qty_pct"])
                    fill = close * (1 - SLIPPAGE)
                    proceeds = fill * sell_qty * (1 - COMMISSION - STT)
                    pnl = (fill - entry_price) / entry_price
                    cash += proceeds
                    position_qty -= sell_qty
                    trades.append({"reason": action["reason"], "pnl_pct": pnl,
                                   "entry_price": entry_price, "exit_price": fill})
                    if position_qty == 0:
                        entry_price = 0.0

            equity_history.append(cash + position_qty * df["Close"].iloc[i])

        if position_qty > 0:
            last_close = df["Close"].iloc[-1]
            proceeds = last_close * position_qty * (1 - COMMISSION - STT - SLIPPAGE)
            cash += proceeds

        total_return = (cash - self._cash) / self._cash
        win_rate = sum(1 for t in trades if t["pnl_pct"] > 0) / len(trades) if trades else 0
        pnls = [t["pnl_pct"] for t in trades]
        sharpe = (np.mean(pnls) / np.std(pnls) * np.sqrt(252)) if len(pnls) > 1 and np.std(pnls) > 0 else 0

        equity_curve = np.array(equity_history)
        rolling_max = np.maximum.accumulate(equity_curve)
        drawdowns = (equity_curve - rolling_max) / rolling_max
        max_drawdown = float(drawdowns.min()) if len(drawdowns) > 0 else 0.0

        return {
            "total_return": round(total_return, 4),
            "final_cash": round(cash, 2),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe, 4),
            "win_rate": round(win_rate, 4),
            "trade_count": len(trades),
            "trades": trades,
        }
