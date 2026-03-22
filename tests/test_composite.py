# tests/test_composite.py
from signals.composite import CompositeScore, SignalStrength

def test_strong_signal_when_score_ge_14():
    cs = CompositeScore(tech_score=6, vol_score=5, chips_score=4)
    assert cs.total == 15
    assert cs.strength == SignalStrength.STRONG

def test_watch_when_score_10_to_13():
    cs = CompositeScore(tech_score=4, vol_score=4, chips_score=4)
    assert cs.total == 12
    assert cs.strength == SignalStrength.WATCH

def test_weak_when_score_below_10():
    cs = CompositeScore(tech_score=1, vol_score=2, chips_score=3)
    assert cs.total == 6
    assert cs.strength == SignalStrength.WEAK

def test_max_score_is_25():
    cs = CompositeScore(tech_score=9, vol_score=6, chips_score=10)
    assert cs.total == 25

def test_chips_score_ignored_when_unavailable():
    cs = CompositeScore(tech_score=8, vol_score=5, chips_score=None)
    assert cs.total == 13
    assert cs.chips_available is False
