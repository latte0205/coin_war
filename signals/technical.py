# signals/technical.py
import pandas as pd
import ta


class TechnicalSignals:
    def __init__(self, df: pd.DataFrame):
        self._df = df.copy()

    def score(self) -> tuple[int, dict]:
        df = self._df
        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        flags = {}
        total = 0

        # KD 黃金交叉 (+2)
        stoch = ta.momentum.StochasticOscillator(high, low, close, n=9, d_n=3)
        k = stoch.stoch()
        d = stoch.stoch_signal()
        kd_cross = (k.shift(1) < d.shift(1)) & (k > d)
        flags["kd_cross"] = bool(kd_cross.iloc[-1])
        if flags["kd_cross"]:
            total += 2

        # MACD 黃金交叉 (+2)
        macd_ind = ta.trend.MACD(close)
        macd_line = macd_ind.macd()
        signal_line = macd_ind.macd_signal()
        macd_cross = (macd_line.shift(1) < signal_line.shift(1)) & (macd_line > signal_line)
        flags["macd_cross"] = bool(macd_cross.iloc[-1])
        if flags["macd_cross"]:
            total += 2

        # RSI 超賣反彈 (+2): check if bounce from oversold occurred in last 10 bars
        rsi = ta.momentum.RSIIndicator(close, n=14).rsi()
        rsi_bounce = (rsi.shift(1) < 30) & (rsi > 30)
        flags["rsi_bounce"] = bool(rsi_bounce.iloc[-10:].any())
        if flags["rsi_bounce"]:
            total += 2

        # 布林通道突破 (+1)
        bb = ta.volatility.BollingerBands(close, n=20, ndev=2)
        bb_break = close > bb.bollinger_hband()
        flags["bb_break"] = bool(bb_break.iloc[-1])
        if flags["bb_break"]:
            total += 1

        # 均線多頭排列 (+2)
        if len(close) >= 60:
            ma5 = close.rolling(5).mean().iloc[-1]
            ma10 = close.rolling(10).mean().iloc[-1]
            ma20 = close.rolling(20).mean().iloc[-1]
            ma60 = close.rolling(60).mean().iloc[-1]
            flags["ma_bull"] = bool(ma5 > ma10 > ma20 > ma60)
        else:
            flags["ma_bull"] = False
        if flags["ma_bull"]:
            total += 2

        return total, flags
