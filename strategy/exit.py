# strategy/exit.py


class ExitSignal:
    def __init__(self, entry_price: float, config: dict):
        self._entry = entry_price
        self._cfg = config["exit"]
        self._tp1_triggered = False

    def check(self, current_price: float, days_held: int,
              current_score: int) -> dict:
        pnl = (current_price - self._entry) / self._entry

        # 停損
        if pnl <= self._cfg["stop_loss_pct"]:
            return {"exit": True, "reason": "stop_loss", "qty_pct": 1.0}

        # 訊號停損
        if current_score < 6:
            return {"exit": True, "reason": "signal_stop", "qty_pct": 1.0}

        # 時間停損
        if days_held >= self._cfg["time_stop_days"] and pnl < 0.05:
            return {"exit": True, "reason": "time_stop", "qty_pct": 1.0}

        # 分批停利 1
        if not self._tp1_triggered and pnl >= self._cfg["take_profit_1_pct"]:
            self._tp1_triggered = True
            return {"exit": True, "reason": "take_profit_1",
                    "qty_pct": self._cfg["take_profit_1_qty_pct"]}

        # 分批停利 2
        if self._tp1_triggered and pnl >= self._cfg["take_profit_2_pct"]:
            return {"exit": True, "reason": "take_profit_2", "qty_pct": 1.0}

        return {"exit": False, "reason": None, "qty_pct": 0.0}
