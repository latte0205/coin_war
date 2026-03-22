# tests/test_technical.py
import pandas as pd
import numpy as np
import pytest
from signals.technical import TechnicalSignals

def make_df(closes, volumes=None):
    n = len(closes)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    highs = [c * 1.02 for c in closes]
    lows = [c * 0.98 for c in closes]
    vols = volumes or [100_000] * n
    return pd.DataFrame({
        "Open": closes, "High": highs, "Low": lows,
        "Close": closes, "Volume": vols
    }, index=idx)

def test_ma_bull_arrangement_true():
    closes = list(range(50, 160))  # 110 bars ascending
    df = make_df(closes)
    sig = TechnicalSignals(df)
    score, flags = sig.score()
    assert flags["ma_bull"]

def test_ma_bull_arrangement_false():
    closes = list(range(150, 40, -1))
    df = make_df(closes)
    sig = TechnicalSignals(df)
    score, flags = sig.score()
    assert not flags["ma_bull"]

def test_score_returns_int_between_0_and_9():
    closes = list(range(100, 210))
    df = make_df(closes)
    sig = TechnicalSignals(df)
    score, _ = sig.score()
    assert 0 <= score <= 9

def test_rsi_oversold_bounce():
    closes = [100.0] * 20
    for _ in range(12):
        closes.append(closes[-1] * 0.97)
    for _ in range(10):
        closes.append(closes[-1] * 1.03)
    df = make_df(closes)
    sig = TechnicalSignals(df)
    _, flags = sig.score()
    assert flags["rsi_bounce"] is True
