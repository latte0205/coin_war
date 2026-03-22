# signals/composite.py
from dataclasses import dataclass
from enum import Enum


class SignalStrength(Enum):
    STRONG = "strong"   # >= 14
    WATCH = "watch"     # 10-13
    WEAK = "weak"       # < 10


@dataclass
class CompositeScore:
    tech_score: int
    vol_score: int
    chips_score: int | None  # None = chips data unavailable

    @property
    def chips_available(self) -> bool:
        return self.chips_score is not None

    @property
    def total(self) -> int:
        return self.tech_score + self.vol_score + (self.chips_score or 0)

    @property
    def strength(self) -> SignalStrength:
        if self.total >= 14:
            return SignalStrength.STRONG
        elif self.total >= 10:
            return SignalStrength.WATCH
        return SignalStrength.WEAK
