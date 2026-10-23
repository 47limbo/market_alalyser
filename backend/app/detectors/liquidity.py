"""Liquidity: resting buy-side/sell-side levels, equal highs/lows, reference levels and sweeps.

Rules follow Part 2.2 of the research doc.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..models import Candle
from .sessions import session_ranges
from .structure import Swing


@dataclass
class LiquidityLevel:
    kind: str  # "buy-side" (above highs) or "sell-side" (below lows)
    source: str  # swing, equal highs, equal lows, PDH, PDL, Asia high, Asia low
    price: float
    index: int  # candle the level was formed on
    active_from: int  # first candle that may sweep it
    swept_at: int | None = None
    sweep_type: str | None = None  # "sweep" (closed back inside) or "break" (accepted beyond)


@dataclass
class Sweep:
    direction: str  # "bullish" (sell-side taken, closed back above) or "bearish"
    level: float
    source: str
    index: int  # candle that made the extreme
    extreme: float
    confirmed_at: int  # candle whose close got back inside


@dataclass
class LiquidityResult:
    levels: list[LiquidityLevel] = field(default_factory=list)
    sweeps: list[Sweep] = field(default_factory=list)


def equal_levels(swings: list[Swing], atrs: list[float], tolerance_atr: float = 0.1) -> list[LiquidityLevel]:
    """Pairs of consecutive same-type swings within tolerance x ATR of each other."""
    out: list[LiquidityLevel] = []
    for kind in ("high", "low"):
        same = [s for s in swings if s.kind == kind]
        for a, b in zip(same, same[1:]):
            if abs(a.price - b.price) <= tolerance_atr * atrs[b.index]:
                price = max(a.price, b.price) if kind == "high" else min(a.price, b.price)
                out.append(
                    LiquidityLevel(
                        "buy-side" if kind == "high" else "sell-side",
                        "equal highs" if kind == "high" else "equal lows",
                        price,
                        b.index,
                        b.confirmed_at + 1,
                    )
                )
    return out


def previous_day_levels(candles: list[Candle]) -> list[LiquidityLevel]:
    """Previous UTC day high and low, active from the first candle of the next day."""
    days: dict[str, list[int]] = {}
    for i, k in enumerate(candles):
        key = datetime.fromtimestamp(k.t / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        days.setdefault(key, []).append(i)
    keys = sorted(days)
    out: list[LiquidityLevel] = []
    for prev, nxt in zip(keys, keys[1:]):
        idx = days[prev]
        hi_i = max(idx, key=lambda j: candles[j].h)
        lo_i = min(idx, key=lambda j: candles[j].l)
        start = days[nxt][0]
        out.append(LiquidityLevel("buy-side", "PDH", candles[hi_i].h, hi_i, start))
        out.append(LiquidityLevel("sell-side", "PDL", candles[lo_i].l, lo_i, start))
    return out


def asia_levels(candles: list[Candle]) -> list[LiquidityLevel]:
    out: list[LiquidityLevel] = []
    for r in session_ranges(candles, "Asia"):
        start = r["end_index"] + 1
        if start >= len(candles):
            continue
        out.append(LiquidityLevel("buy-side", "Asia high", r["high"], r["high_index"], start))
        out.append(LiquidityLevel("sell-side", "Asia low", r["low"], r["low_index"], start))
    return out


def detect_liquidity(
    candles: list[Candle],
    swings: list[Swing],
    atrs: list[float],
    reclaim_window: int = 3,
    include_reference_levels: bool = True,
) -> LiquidityResult:
    levels = [
        LiquidityLevel("buy-side" if s.kind == "high" else "sell-side", "swing", s.price, s.index, s.confirmed_at + 1)
        for s in swings
    ]
    levels += equal_levels(swings, atrs)
    if include_reference_levels:
        levels += previous_day_levels(candles)
        levels += asia_levels(candles)

    result = LiquidityResult(levels=levels)
    for lv in levels:
        sweep = _check_level(candles, lv, reclaim_window)
        if sweep:
            result.sweeps.append(sweep)
    result.sweeps.sort(key=lambda s: s.confirmed_at)
    return result


def _check_level(candles: list[Candle], lv: LiquidityLevel, window: int) -> Sweep | None:
    """A sweep trades beyond the level and closes back inside within `window` candles.
    Anything else that trades beyond it is a break (liquidity taken and accepted)."""
    above = lv.kind == "buy-side"
    for j in range(lv.active_from, len(candles)):
        k = candles[j]
        pierced = k.h > lv.price if above else k.l < lv.price
        if not pierced:
            continue
        lv.swept_at = j
        extreme = k.h if above else k.l
        for m in range(j, min(len(candles), j + window)):
            km = candles[m]
            extreme = max(extreme, km.h) if above else min(extreme, km.l)
            back_inside = km.c < lv.price if above else km.c > lv.price
            if back_inside:
                lv.sweep_type = "sweep"
                return Sweep("bearish" if above else "bullish", lv.price, lv.source, j, extreme, m)
        lv.sweep_type = "break"
        return None
    return None
