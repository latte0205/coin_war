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
    def _max_score(self) -> int:
        return 25 if self.chips_available else 15

    @property
    def strength(self) -> SignalStrength:
        # Scale thresholds proportionally when chips data is unavailable
        scale = self._max_score / 25
        strong_thresh = round(14 * scale)   # 14 with chips, 8 without
        watch_thresh = round(10 * scale)    # 10 with chips, 6 without
        if self.total >= strong_thresh:
            return SignalStrength.STRONG
        elif self.total >= watch_thresh:
            return SignalStrength.WATCH
        return SignalStrength.WEAK
