# crypto/position_sizer.py


def calculate_amount(balance_usdt: float, cfg: dict) -> float:
    """
    Returns trade size in USDT, or 0.0 if trade should be skipped.

    Rules:
    1. If balance < min_usdt: return 0.0
    2. effective_min = min(balance * min_balance_pct, max_usdt)
    3. amount = clamp(balance, low=effective_min, high=max_usdt)
    """
    max_usdt        = cfg["position"]["max_usdt"]
    min_balance_pct = cfg["position"]["min_balance_pct"]
    min_usdt        = cfg["position"]["min_usdt"]

    if balance_usdt < min_usdt:
        return 0.0

    effective_min = min(balance_usdt * min_balance_pct, max_usdt)
    amount = min(balance_usdt, max_usdt)
    amount = max(amount, effective_min)
    return amount
