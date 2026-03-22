# signals/volume.py
import pandas as pd
import ta


class VolumeSignals:
    def __init__(self, df: pd.DataFrame):
        self._df = df.copy()

    def score(self) -> tuple[int, dict]:
        df = self._df
        close = df["Close"]
        volume = df["Volume"]
        flags = {}
        total = 0

        vol_ma20 = volume.rolling(20).mean()

        # 爆量突破 (+3)
        vol_surge = volume.iloc[-1] > vol_ma20.iloc[-1] * 2
        # bullish: close higher than previous close or higher than open
        is_bullish = (close.iloc[-1] > df["Open"].iloc[-1]) or (
            len(close) >= 2 and close.iloc[-1] > close.iloc[-2]
        )
        flags["vol_breakout"] = bool(vol_surge and is_bullish)
        if flags["vol_breakout"]:
            total += 3

        # 縮量整理後放量 (+2)
        if len(df) >= 26:
            prev5_avg = volume.iloc[-6:-1].mean()
            contracted = prev5_avg < vol_ma20.iloc[-1]
            expanded = volume.iloc[-1] > vol_ma20.iloc[-1] * 1.5
            flags["vol_expand_after_contract"] = bool(contracted and expanded)
        else:
            flags["vol_expand_after_contract"] = False
        if flags["vol_expand_after_contract"]:
            total += 2

        # OBV 創近10日新高 (+1)
        obv = ta.volume.OnBalanceVolumeIndicator(close, volume).on_balance_volume()
        if len(obv.dropna()) >= 11:
            obv_new_high = obv.iloc[-1] == obv.iloc[-11:].max()
            flags["obv_high"] = bool(obv_new_high)
        else:
            flags["obv_high"] = False
        if flags["obv_high"]:
            total += 1

        return total, flags
