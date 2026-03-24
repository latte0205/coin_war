import pytest
from crypto.position_sizer import calculate_amount

CFG = {
    "position": {
        "max_usdt": 1000,
        "min_balance_pct": 0.05,
        "min_usdt": 20,
    }
}


def test_normal_large_balance():
    # balance=5000: effective_min=min(250,1000)=250, amount=min(5000,1000)=1000
    assert calculate_amount(5000.0, CFG) == 1000.0


def test_small_balance_below_max():
    # balance=200: effective_min=min(10,1000)=10, amount=min(200,1000)=200
    assert calculate_amount(200.0, CFG) == 200.0


def test_balance_below_min_usdt():
    # balance=15 < min_usdt=20 → skip
    assert calculate_amount(15.0, CFG) == 0.0


def test_balance_exactly_min_usdt():
    # balance=20 >= min_usdt: effective_min=min(1,1000)=1, amount=min(20,1000)=20
    assert calculate_amount(20.0, CFG) == 20.0


def test_effective_min_never_exceeds_max():
    # balance=100000: effective_min=min(5000,1000)=1000, amount=min(100000,1000)=1000
    assert calculate_amount(100000.0, CFG) == 1000.0


def test_zero_balance():
    assert calculate_amount(0.0, CFG) == 0.0
