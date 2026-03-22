# tests/test_volume.py
import pandas as pd
import pytest
from signals.volume import VolumeSignals

def make_df(closes, volumes):
    n = len(closes)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": closes, "High": [c*1.01 for c in closes],
        "Low": [c*0.99 for c in closes],
        "Close": closes, "Volume": volumes
    }, index=idx)

def test_volume_breakout_detected():
    closes = [100] * 20 + [101]
    volumes = [100_000] * 20 + [250_000]
    df = make_df(closes, volumes)
    sig = VolumeSignals(df)
    score, flags = sig.score()
    assert flags["vol_breakout"]
    assert score >= 3

def test_volume_breakout_not_detected_when_bearish():
    closes = [100] * 20 + [99]
    volumes = [100_000] * 20 + [250_000]
    df = make_df(closes, volumes)
    sig = VolumeSignals(df)
    _, flags = sig.score()
    assert not flags["vol_breakout"]

def test_score_max_6():
    closes = list(range(90, 121))  # 31 items
    volumes = [100_000] * 30 + [350_000]  # 31 items
    df = make_df(closes, volumes)
    sig = VolumeSignals(df)
    score, _ = sig.score()
    assert 0 <= score <= 6
