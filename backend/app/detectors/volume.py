"""Volume tools: session VWAP with bands, relative volume, volume profile (Part 2.5)."""

from datetime import datetime, timezone
from math import sqrt

from ..models import Candle


def session_vwap(candles: list[Candle]) -> list[dict]:
    """VWAP reset at each UTC day, with 1 and 2 standard deviation bands (volume weighted)."""
    out: list[dict] = []
    day = None
    pv = vol = pv2 = 0.0
    for k in candles:
        d = datetime.fromtimestamp(k.t / 1000, tz=timezone.utc).date()
        if d != day:
            day, pv, vol, pv2 = d, 0.0, 0.0, 0.0
        tp = (k.h + k.l + k.c) / 3
        pv += tp * k.v
        pv2 += tp * tp * k.v
        vol += k.v
        if vol == 0:
            out.append({"t": k.t, "vwap": tp, "sd": 0.0})
            continue
        vwap = pv / vol
        sd = sqrt(max(0.0, pv2 / vol - vwap * vwap))
        out.append({"t": k.t, "vwap": vwap, "sd": sd})
    return out


def relative_volume(candles: list[Candle], lookback: int = 20) -> list[float | None]:
    """Volume vs the average of the previous `lookback` candles (None until enough history)."""
    out: list[float | None] = []
    for i, k in enumerate(candles):
        if i < lookback:
            out.append(None)
            continue
        avg = sum(x.v for x in candles[i - lookback : i]) / lookback
        out.append(k.v / avg if avg > 0 else None)
    return out


def volume_profile(candles: list[Candle], bins: int = 40, value_area: float = 0.7) -> dict | None:
    """Spread each candle's volume evenly over the price bins its range covers.
    Returns the bins, point of control and value area high/low."""
    if not candles:
        return None
    lo = min(k.l for k in candles)
    hi = max(k.h for k in candles)
    if hi <= lo:
        return None
    step = (hi - lo) / bins
    vols = [0.0] * bins
    for k in candles:
        a = min(bins - 1, int((k.l - lo) / step))
        b = min(bins - 1, int((k.h - lo) / step))
        share = k.v / (b - a + 1)
        for j in range(a, b + 1):
            vols[j] += share
    poc = max(range(bins), key=lambda j: vols[j])

    total = sum(vols)
    inside = vols[poc]
    lo_i = hi_i = poc
    while total > 0 and inside / total < value_area and (lo_i > 0 or hi_i < bins - 1):
        below = vols[lo_i - 1] if lo_i > 0 else -1
        above = vols[hi_i + 1] if hi_i < bins - 1 else -1
        if above >= below:
            hi_i += 1
            inside += vols[hi_i]
        else:
            lo_i -= 1
            inside += vols[lo_i]

    return {
        "bins": [{"low": lo + j * step, "high": lo + (j + 1) * step, "volume": vols[j]} for j in range(bins)],
        "poc": lo + (poc + 0.5) * step,
        "vah": lo + (hi_i + 1) * step,
        "val": lo + lo_i * step,
    }
