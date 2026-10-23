"""Basic indicators the detectors depend on."""

from ..models import Candle


def true_ranges(candles: list[Candle]) -> list[float]:
    out = []
    for i, k in enumerate(candles):
        if i == 0:
            out.append(k.range)
        else:
            prev_close = candles[i - 1].c
            out.append(max(k.h - k.l, abs(k.h - prev_close), abs(k.l - prev_close)))
    return out


def atr(candles: list[Candle], period: int = 14) -> list[float]:
    """Wilder's average true range. Early values use the running mean so every index has a value."""
    trs = true_ranges(candles)
    out: list[float] = []
    for i, tr in enumerate(trs):
        if i < period:
            out.append(sum(trs[: i + 1]) / (i + 1))
        else:
            out.append((out[-1] * (period - 1) + tr) / period)
    return out
