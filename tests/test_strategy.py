# tests/test_strategy.py
import pandas as pd
import pytest
from signals.composite import CompositeScore
from strategy.entry import EntryFilter
from strategy.exit import ExitSignal

def make_price_df(closes):
    idx = pd.date_range("2023-01-02", periods=len(closes), freq="B")
    vols = [100_000] * len(closes)
    vol_ma = 80_000
    return pd.DataFrame({"Close": closes, "Volume": vols,
                          "vol_ma20": [vol_ma]*len(closes)}, index=idx)

# --- Entry ---
def test_entry_allowed_when_all_conditions_met():
    cs = CompositeScore(tech_score=6, vol_score=5, chips_score=4)  # 15 >= 14
    closes = list(range(90, 106))  # ascending trend
    df = make_price_df(closes)
    ef = EntryFilter(config={"thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8}})
    assert ef.should_enter(cs, df) is True

def test_entry_blocked_when_score_too_low():
    cs = CompositeScore(tech_score=3, vol_score=2, chips_score=2)  # 7 < 14
    df = make_price_df(list(range(90, 106)))
    ef = EntryFilter(config={"thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8}})
    assert ef.should_enter(cs, df) is False

def test_entry_blocked_when_price_below_ma5():
    cs = CompositeScore(tech_score=6, vol_score=5, chips_score=4)
    closes = list(range(106, 90, -1))  # descending trend
    df = make_price_df(closes)
    ef = EntryFilter(config={"thresholds": {"strong_signal": 14, "volume_filter_ratio": 0.8}})
    assert ef.should_enter(cs, df) is False

# --- Exit ---
def test_stop_loss_triggered():
    es = ExitSignal(entry_price=100.0, config={
        "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
                 "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
                 "time_stop_days": 20}})
    action = es.check(current_price=92.0, days_held=3, current_score=12)
    assert action["exit"] is True
    assert action["reason"] == "stop_loss"
    assert action["qty_pct"] == 1.0

def test_partial_take_profit_at_15pct():
    es = ExitSignal(entry_price=100.0, config={
        "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
                 "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
                 "time_stop_days": 20}})
    action = es.check(current_price=116.0, days_held=5, current_score=15)
    assert action["exit"] is True
    assert action["reason"] == "take_profit_1"
    assert action["qty_pct"] == 0.5

def test_no_exit_when_conditions_not_met():
    es = ExitSignal(entry_price=100.0, config={
        "exit": {"stop_loss_pct": -0.07, "take_profit_1_pct": 0.15,
                 "take_profit_1_qty_pct": 0.50, "take_profit_2_pct": 0.20,
                 "time_stop_days": 20}})
    action = es.check(current_price=105.0, days_held=5, current_score=14)
    assert action["exit"] is False
