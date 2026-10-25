"""Made-up prices for demo mode, so the sector board, shortlist and alignment can be seen offline.

A one-factor model: every name follows the market, its niche and some noise of its own, so betas and
correlations come out realistic. Today's moves are set by hand to replay the strategy doc's example: Meta
falls on its spending plans, tech turns red and money rotates into healthcare and staples.
"""

import random
import time

from ..models import Candle
from .board import MACRO_SYMBOLS
from .universe import BENCHMARK, NICHES, universe

DAYS = 200
TODAY = {  # % move today, by symbol
    "META": -4.5, "XLK": -1.1, "XLC": -1.6, "IGV": -0.9, "SMH": 0.6, "NVDA": 2.4, "AVGO": 2.1, "XLU": 1.3,
    "CEG": 3.2, "VST": 3.6, "XLV": 1.5, "UNH": 2.6, "LLY": 1.8, "XLP": 0.9, "SPY": -0.2, "QQQ": -0.8,
    "^TNX": 1.6, "CL=F": 1.4, "^VIX": 6.0, "XLE": 0.7,
}
LEVEL = {"^TNX": 4.15, "^VIX": 17.0, "CL=F": 74.0, "DX-Y.NYB": 99.0, "HG=F": 4.6, "GC=F": 2650.0, "HYG": 79.0}


def demo_daily(seed: int = 11) -> dict[str, list[Candle]]:
    rnd = random.Random(seed)
    market = [rnd.gauss(0.04, 1.0) for _ in range(DAYS)]
    factor = {n.etf: [m * rnd.uniform(0.8, 1.3) + rnd.gauss(0, 0.7) for m in market] for n in NICHES}
    factor[BENCHMARK] = market
    rets: dict[str, list[float]] = {BENCHMARK: market}
    for n in NICHES:
        rets[n.etf] = factor[n.etf]
        for h in n.holdings:
            if h not in rets:
                beta = rnd.uniform(1.0, 1.6)
                rets[h] = [f * beta + rnd.gauss(0, 0.9) for f in factor[n.etf]]
    for sym in MACRO_SYMBOLS:
        rets[sym] = [rnd.gauss(0, 0.8) for _ in range(DAYS)]
    for sym, move in TODAY.items():
        if sym in rets:
            rets[sym][-1] = move

    day = 86_400_000
    start = (int(time.time() * 1000) // day) * day - (DAYS - 1) * day + 14 * 3_600_000
    out = {}
    for sym in universe() + MACRO_SYMBOLS:
        r = rets.get(sym)
        if not r:
            continue
        price = LEVEL.get(sym, rnd.uniform(40, 400))
        volume = rnd.uniform(3e6, 40e6)
        bars = []
        for i, x in enumerate(r):
            if sym == "^TNX":
                o, c = price, price + x * 0.05  # a yield moves in points, about 5 bp a day
            else:
                o, c = price, price * (1 + x / 100)
            hi, lo = max(o, c) * (1 + abs(rnd.gauss(0, 0.006))), min(o, c) * (1 - abs(rnd.gauss(0, 0.006)))
            v = volume * rnd.uniform(0.7, 1.3) * (1.8 if i == DAYS - 1 and abs(x) > 1 else 1)
            bars.append(Candle(start + i * day, round(o, 4), round(hi, 4), round(lo, 4), round(c, 4), round(v)))
            price = c
        out[sym] = bars
    return out


DEMO_HEADLINES = {"META": ["Meta raises capex outlook as AI data center spending climbs; shares slide"]}
