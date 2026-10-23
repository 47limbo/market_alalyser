"""Price zones: fair value gaps, order blocks, breakers, premium/discount and OTE.

Rules follow Part 2.3 of the research doc.
"""

from dataclasses import dataclass

from ..models import Candle
from .structure import StructureEvent, Swing, is_displacement


@dataclass
class FairValueGap:
    direction: str  # "bullish" or "bearish"
    index: int  # middle candle of the three
    top: float
    bottom: float
    status: str = "open"  # open, partial, filled, inverted
    fill_pct: float = 0.0
    touched_at: int | None = None
    filled_at: int | None = None

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class OrderBlock:
    direction: str  # "bullish" or "bearish"
    index: int  # the order block candle
    top: float
    bottom: float
    event_index: int  # candle of the BOS/CHoCH it caused
    event_type: str
    status: str = "active"  # active, mitigated, breaker
    mitigated_at: int | None = None
    broken_at: int | None = None


def detect_fvgs(candles: list[Candle], atrs: list[float], min_atr_mult: float = 0.25) -> list[FairValueGap]:
    gaps: list[FairValueGap] = []
    for i in range(2, len(candles)):
        a, c = candles[i - 2], candles[i]
        min_size = min_atr_mult * atrs[i]
        if a.h < c.l and c.l - a.h >= min_size:
            gaps.append(FairValueGap("bullish", i - 1, top=c.l, bottom=a.h))
        elif a.l > c.h and a.l - c.h >= min_size:
            gaps.append(FairValueGap("bearish", i - 1, top=a.l, bottom=c.h))

    for g in gaps:
        _track_fvg(candles, g)
    return gaps


def _track_fvg(candles: list[Candle], g: FairValueGap) -> None:
    size = g.top - g.bottom
    for j in range(g.index + 2, len(candles)):
        k = candles[j]
        if g.direction == "bullish":
            depth = g.top - k.l  # how far price came back down into the gap
            closed_through = k.c < g.bottom
        else:
            depth = k.h - g.bottom
            closed_through = k.c > g.top
        if depth <= 0:
            continue
        if g.touched_at is None:
            g.touched_at = j
        g.fill_pct = max(g.fill_pct, min(1.0, depth / size))
        if closed_through:
            g.status, g.filled_at, g.fill_pct = "inverted", j, 1.0
            return
        if g.fill_pct >= 1.0 and g.status != "filled":
            g.status, g.filled_at = "filled", j
        elif g.status == "open":
            g.status = "partial"


def detect_order_blocks(
    candles: list[Candle],
    atrs: list[float],
    events: list[StructureEvent],
    search_back: int = 5,
) -> list[OrderBlock]:
    """For each structure break that came with displacement, the order block is the last
    opposite-colour candle at or before the start of the impulse.

    Bullish: find the lowest low between the broken swing and the break, then the last
    down-close candle at or before the first bullish displacement candle after that low.
    """
    blocks: list[OrderBlock] = []
    for ev in events:
        if not ev.displacement:
            continue
        lo, hi = ev.swing_index, ev.index
        if ev.direction == "bullish":
            origin = min(range(lo, hi + 1), key=lambda j: candles[j].l)
            impulse = next(
                (j for j in range(origin, hi + 1) if candles[j].bullish and is_displacement(candles[j], atrs[j])), hi
            )
            pick = _last_matching(candles, max(0, origin - search_back), impulse - 1, lambda k: k.bearish)
        else:
            origin = max(range(lo, hi + 1), key=lambda j: candles[j].h)
            impulse = next(
                (j for j in range(origin, hi + 1) if candles[j].bearish and is_displacement(candles[j], atrs[j])), hi
            )
            pick = _last_matching(candles, max(0, origin - search_back), impulse - 1, lambda k: k.bullish)
        if pick is None:
            continue
        k = candles[pick]
        ob = OrderBlock(ev.direction, pick, top=k.h, bottom=k.l, event_index=ev.index, event_type=ev.type)
        _track_order_block(candles, ob)
        blocks.append(ob)
    return blocks


def _last_matching(candles, start: int, end: int, pred) -> int | None:
    for j in range(end, start - 1, -1):
        if pred(candles[j]):
            return j
    return None


def _track_order_block(candles: list[Candle], ob: OrderBlock) -> None:
    for j in range(ob.event_index + 1, len(candles)):
        k = candles[j]
        if ob.direction == "bullish":
            if k.c < ob.bottom:
                ob.status, ob.broken_at = "breaker", j
                return
            if ob.mitigated_at is None and k.l <= ob.top:
                ob.status, ob.mitigated_at = "mitigated", j
        else:
            if k.c > ob.top:
                ob.status, ob.broken_at = "breaker", j
                return
            if ob.mitigated_at is None and k.h >= ob.bottom:
                ob.status, ob.mitigated_at = "mitigated", j


def dealing_range(candles: list[Candle], swings: list[Swing], trend: str | None) -> dict | None:
    """Range from the latest confirmed swing high and swing low, stretched to any price made beyond
    them since, so the current price always sits inside it. Adds premium/discount and OTE bands.

    OTE is the 62% to 79% retracement measured in the trend direction:
    for a bullish trend it sits below equilibrium (a pullback to buy), for bearish above it.
    """
    last_index = len(candles) - 1
    price = candles[-1].c
    confirmed = [s for s in swings if s.confirmed_at <= last_index]
    highs = [s for s in confirmed if s.kind == "high"]
    lows = [s for s in confirmed if s.kind == "low"]
    if not highs or not lows:
        return None
    hi_swing, lo_swing = highs[-1], lows[-1]
    start = min(hi_swing.index, lo_swing.index)
    hi = max(k.h for k in candles[hi_swing.index :])
    lo = min(k.l for k in candles[lo_swing.index :])
    if hi <= lo:
        return None
    span = hi - lo
    eq = lo + span / 2
    if trend == "bearish":
        ote = (lo + 0.62 * span, lo + 0.79 * span)
    else:
        ote = (hi - 0.79 * span, hi - 0.62 * span)
    position = (price - lo) / span
    zone = "premium" if position > 0.5 else "discount" if position < 0.5 else "equilibrium"
    return {
        "high": hi,
        "low": lo,
        "start_index": start,
        "equilibrium": eq,
        "ote_low": min(ote),
        "ote_high": max(ote),
        "position": round(position, 4),
        "zone": zone,
        "in_ote": min(ote) <= price <= max(ote),
    }
