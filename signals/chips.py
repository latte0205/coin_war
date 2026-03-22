# signals/chips.py
import pandas as pd


class ChipsSignals:
    def __init__(self, inst_df: pd.DataFrame, margin_df: pd.DataFrame,
                 price_df: pd.DataFrame):
        self._inst = inst_df
        self._margin = margin_df
        self._price = price_df

    def score(self) -> tuple[int, dict]:
        flags = {}
        total = 0

        foreign = self._inst[self._inst["name"] == "Foreign_Investor"].sort_values("date")
        trust = self._inst[self._inst["name"] == "Investment_Trust"].sort_values("date")

        # 外資連買 3 日以上 (+3)
        if len(foreign) >= 3:
            last3 = foreign["diff"].iloc[-3:]
            flags["foreign_consecutive"] = bool((last3 > 0).all())
        else:
            flags["foreign_consecutive"] = False
        if flags["foreign_consecutive"]:
            total += 3

        # 投信連買 2 日以上 (+2)
        if len(trust) >= 2:
            last2 = trust["diff"].iloc[-2:]
            flags["trust_consecutive"] = bool((last2 > 0).all())
        else:
            flags["trust_consecutive"] = False
        if flags["trust_consecutive"]:
            total += 2

        # 法人合力買超 (+3)
        if not foreign.empty and not trust.empty:
            last_date = max(foreign["date"].iloc[-1], trust["date"].iloc[-1])
            f_today = foreign[foreign["date"] == last_date]["diff"].sum()
            t_today = trust[trust["date"] == last_date]["diff"].sum()
            flags["joint_buy"] = bool(f_today > 0 and t_today > 0)
        else:
            flags["joint_buy"] = False
        if flags["joint_buy"]:
            total += 3

        # 融資減少 + 股價上漲 (+2)
        if len(self._margin) >= 2 and len(self._price) >= 2:
            mb = self._margin["MarginPurchaseBalance"]
            margin_dec = (mb.iloc[-2] - mb.iloc[-1]) / mb.iloc[-2] > 0.01 if mb.iloc[-2] != 0 else False
            price_up = self._price["Close"].iloc[-1] > self._price["Close"].iloc[-2]
            flags["margin_reduce_price_up"] = bool(margin_dec and price_up)
        else:
            flags["margin_reduce_price_up"] = False
        if flags["margin_reduce_price_up"]:
            total += 2

        return total, flags
