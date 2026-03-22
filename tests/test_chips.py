# tests/test_chips.py
import pandas as pd
import pytest
from signals.chips import ChipsSignals

def make_inst(foreign_values, trust_values):
    rows = []
    n = max(len(foreign_values), len(trust_values), 1)
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    for i, v in enumerate(foreign_values):
        rows.append({"date": dates[i], "name": "Foreign_Investor", "buy": max(v,0)*1e6, "sell": max(-v,0)*1e6, "diff": v*1e6})
    for i, v in enumerate(trust_values):
        rows.append({"date": dates[i], "name": "Investment_Trust", "buy": max(v,0)*1e6, "sell": max(-v,0)*1e6, "diff": v*1e6})
    return pd.DataFrame(rows)

def make_margin(margin_balance_changes):
    dates = pd.date_range("2024-01-02", periods=len(margin_balance_changes), freq="B")
    rows = [{"date": d, "MarginPurchaseBalance": 10000 + sum(margin_balance_changes[:i+1])}
            for i, d in enumerate(dates)]
    return pd.DataFrame(rows)

def test_foreign_consecutive_buy_3days():
    inst = make_inst([100, 200, 300], [50, 60])
    sig = ChipsSignals(inst_df=inst, margin_df=make_margin([0,0,0]), price_df=pd.DataFrame())
    _, flags = sig.score()
    assert flags["foreign_consecutive"]

def test_no_foreign_consecutive_when_gap():
    inst = make_inst([100, -50, 300], [])
    sig = ChipsSignals(inst_df=inst, margin_df=make_margin([0,0,0]), price_df=pd.DataFrame())
    _, flags = sig.score()
    assert not flags["foreign_consecutive"]

def test_score_max_10():
    inst = make_inst([100]*5, [50]*5)
    sig = ChipsSignals(inst_df=inst, margin_df=make_margin([-200, -200, -200]), price_df=pd.DataFrame({"Close": [100,101,102]}))
    score, _ = sig.score()
    assert 0 <= score <= 10
