"""Market structure: swings, trend, break of structure (BOS), change of character (CHoCH), displacement.

Rules follow Part 2.1 of the research doc.
"""

from dataclasses import dataclass, field

from ..models import Candle


@dataclass
class Swing:
    index: int
    kind: str  # "high" or "low"
    price: float
    confirmed_at: int  # index of the candle that confirms the swing (index + lookback)
    broken_at: int | None = None
    swept_at: int | None = None


@dataclass
class StructureEvent:
    type: str  # "BOS" or "CHoCH"
    direction: str  # "bullish" or "bearish"
    level: float
    swing_index: int
    index: int  # candle whose close broke the level
    displacement: bool = False


@dataclass
class StructureResult:
    swings: list[Swing] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    trend: str | None = None  # trend after the last candle


def find_swings(candles: list[Candle], lookback: int = 3) -> list[Swing]:
    """Fractal swings: a high above the highs of `lookback` candles on each side (and the reverse for lows).

    Ties with a neighbour do not count, so flat tops produce one swing at most.
    """
    swings: list[Swing] = []
    n = lookback
    for i in range(n, len(candles) - n):
        left = candles[i - n : i]
        right = candles[i + 1 : i + n + 1]
        k = candles[i]
        if all(k.h > x.h for x in left) and all(k.h > x.h for x in right):
            swings.append(Swing(i, "high", k.h, i + n))
        if all(k.l < x.l for x in left) and all(k.l < x.l for x in right):
            swings.append(Swing(i, "low", k.l, i + n))
    return swings


def is_displacement(candle: Candle, atr_value: float, body_mult: float = 1.5, max_wick_ratio: float = 0.3) -> bool:
    if candle.range == 0 or atr_value <= 0:
        return False
    wicks = candle.range - candle.body
    return candle.body >= body_mult * atr_value and wicks / candle.range <= max_wick_ratio


def detect_structure(
    candles: list[Candle],
    atrs: list[float],
    lookback: int = 3,
    displacement_window: int = 3,
) -> StructureResult:
    """Walk candles in order and emit BOS / CHoCH when a body close passes the latest confirmed swing.

    A swing only becomes breakable once it is confirmed, so no event uses future candles.
    In an uptrend a close above the last swing high is a BOS; a close below the last swing low is a CHoCH.
    With no trend yet, the first break sets the trend and is labelled BOS.
    """
    swings = find_swings(candles, lookback)
    by_confirm: dict[int, list[Swing]] = {}
    for s in swings:
        by_confirm.setdefault(s.confirmed_at, []).append(s)

    result = StructureResult(swings=swings)
    last_high: Swing | None = None
    last_low: Swing | None = None
    trend: str | None = None

    for i, k in enumerate(candles):
        for s in by_confirm.get(i, []):
            if s.kind == "high":
                last_high = s
            else:
                last_low = s

        if last_high and last_high.broken_at is None and k.c > last_high.price and last_high.index < i:
            ev_type = "CHoCH" if trend == "bearish" else "BOS"
            last_high.broken_at = i
            result.events.append(
                StructureEvent(ev_type, "bullish", last_high.price, last_high.index, i,
                               _has_displacement(candles, atrs, last_high.index, i, "bullish", displacement_window))
            )
            trend = "bullish"
        elif last_low and last_low.broken_at is None and k.c < last_low.price and last_low.index < i:
            ev_type = "CHoCH" if trend == "bullish" else "BOS"
            last_low.broken_at = i
            result.events.append(
                StructureEvent(ev_type, "bearish", last_low.price, last_low.index, i,
                               _has_displacement(candles, atrs, last_low.index, i, "bearish", displacement_window))
            )
            trend = "bearish"

    result.trend = trend
    return result


def _has_displacement(candles, atrs, start: int, end: int, direction: str, window: int) -> bool:
    lo = max(start + 1, end - window + 1)
    for j in range(lo, end + 1):
        k = candles[j]
        right_way = k.bullish if direction == "bullish" else k.bearish
        if right_way and is_displacement(k, atrs[j]):
            return True
    return False
