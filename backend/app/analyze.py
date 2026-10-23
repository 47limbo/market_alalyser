"""Run every technical detector over a candle series and return one JSON-ready report."""

from dataclasses import asdict

from .detectors.indicators import atr
from .detectors.liquidity import detect_liquidity
from .detectors.sessions import killzone_for, killzone_spans
from .detectors.structure import detect_structure
from .detectors.volume import relative_volume, session_vwap, volume_profile
from .detectors.zones import dealing_range, detect_fvgs, detect_order_blocks
from .models import Candle


def analyse(candles: list[Candle], swing_lookback: int = 3, profile_candles: int = 200) -> dict:
    if len(candles) < 2 * swing_lookback + 3:
        raise ValueError("not enough candles to analyse")

    atrs = atr(candles)
    structure = detect_structure(candles, atrs, lookback=swing_lookback)
    fvgs = detect_fvgs(candles, atrs)
    blocks = detect_order_blocks(candles, atrs, structure.events)
    liquidity = detect_liquidity(candles, structure.swings, atrs)
    last = candles[-1]
    rvol = relative_volume(candles)

    def t(i: int | None) -> int | None:
        return candles[i].t if i is not None else None

    return {
        "last": {
            "t": last.t,
            "price": last.c,
            "atr": atrs[-1],
            "rvol": rvol[-1],
            "killzone": killzone_for(last.t),
        },
        "trend": structure.trend,
        "swings": [{**asdict(s), "time": t(s.index)} for s in structure.swings],
        "structure": [{**asdict(e), "time": t(e.index), "swing_time": t(e.swing_index)} for e in structure.events],
        "fvgs": [{**asdict(g), "time": t(g.index), "filled_time": t(g.filled_at)} for g in fvgs],
        "order_blocks": [{**asdict(b), "time": t(b.index), "end_time": t(b.broken_at)} for b in blocks],
        "liquidity": [
            {**asdict(lv), "time": t(lv.index), "swept_time": t(lv.swept_at)} for lv in liquidity.levels
        ],
        "sweeps": [{**asdict(s), "time": t(s.index)} for s in liquidity.sweeps],
        "dealing_range": _with_time(dealing_range(candles, structure.swings, structure.trend), t),
        "killzones": [
            {**k, "start_time": t(k["start_index"]), "end_time": t(k["end_index"])} for k in killzone_spans(candles)
        ],
        "vwap": session_vwap(candles),
        "volume_profile": volume_profile(candles[-profile_candles:]),
    }


def _with_time(dr: dict | None, t) -> dict | None:
    return {**dr, "start_time": t(dr["start_index"])} if dr else None
