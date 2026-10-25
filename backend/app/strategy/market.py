"""Prices for the sector board: daily bars and today's intraday move for many symbols, fetched from Yahoo
in parallel and cached, plus the small statistics the strategy uses (returns, beta, correlation, ATR)."""

import asyncio
import math
import time

import httpx

from .. import yahoo
from ..models import Candle

DAILY_SECONDS = 600
INTRADAY_SECONDS = 120
PARALLEL = 8
_cache: dict[tuple[str, str], tuple[float, list[Candle]]] = {}


async def _one(http, sem, symbol: str, kind: str) -> tuple[str, list[Candle] | None]:
    key = (symbol, kind)
    ttl = DAILY_SECONDS if kind == "daily" else INTRADAY_SECONDS
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return symbol, hit[1]
    async with sem:
        try:
            if kind == "daily":
                bars = await yahoo.fetch_candles(symbol, "1d", 200, client=http, rng="1y")
            else:
                bars = await yahoo.fetch_candles(symbol, "5m", 400, client=http, rng="2d")
        except (yahoo.YahooError, ValueError):
            return symbol, hit[1] if hit else None  # an old copy beats nothing
    _cache[key] = (time.time(), bars)
    return symbol, bars


async def fetch_many(symbols: list[str], kind: str = "daily") -> dict[str, list[Candle]]:
    """{symbol: bars} for every symbol Yahoo answered; the rest are simply missing."""
    sem = asyncio.Semaphore(PARALLEL)
    async with httpx.AsyncClient(timeout=15, headers=yahoo.HEADERS) as http:
        got = await asyncio.gather(*(_one(http, sem, s, kind) for s in symbols))
    return {s: bars for s, bars in got if bars}


# ---- statistics on closes ----

def closes(bars: list[Candle]) -> list[float]:
    return [b.c for b in bars]


def pct(a: float, b: float) -> float:
    return (b / a - 1) * 100 if a else 0.0


def ret(bars: list[Candle], back: int, end: int = 0) -> float | None:
    """% change over `back` bars, ending `end` bars before the last one."""
    j = len(bars) - 1 - end
    return pct(bars[j - back].c, bars[j].c) if j - back >= 0 else None


def daily_returns(bars: list[Candle]) -> list[float]:
    return [pct(a.c, b.c) for a, b in zip(bars, bars[1:])]


def beta_corr(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Beta and correlation of ys (the stock) to xs (the market or niche), on the overlapping tail."""
    n = min(len(xs), len(ys))
    if n < 20:
        return None, None
    xs, ys = xs[-n:], ys[-n:]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    vx = sum((x - mx) ** 2 for x in xs) / n
    vy = sum((y - my) ** 2 for y in ys) / n
    if vx <= 0 or vy <= 0:
        return None, None
    return cov / vx, cov / math.sqrt(vx * vy)


def stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sma(bars: list[Candle], n: int) -> float | None:
    return sum(b.c for b in bars[-n:]) / n if len(bars) >= n else None


def atr_pct(bars: list[Candle], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    trs = [max(b.h - b.l, abs(b.h - a.c), abs(b.l - a.c)) for a, b in zip(bars[-n - 1:], bars[-n:])]
    return sum(trs) / n / bars[-1].c * 100


def session_fraction(now_ms: int) -> float:
    """How much of the 6.5 hour regular session has passed, for scaling today's volume (1 outside hours)."""
    from ..detectors.sessions import ny_time

    t = ny_time(now_ms)
    minutes = (t.hour - 9) * 60 + t.minute - 30
    if t.weekday() >= 5 or minutes <= 0 or minutes >= 390:
        return 1.0
    return max(0.1, minutes / 390)


def today_move(daily: list[Candle], intraday: list[Candle] | None) -> tuple[float | None, float | None]:
    """(last price, % change vs the previous regular-session close). Uses the intraday bars when they are newer,
    so pre-market and after-hours moves count."""
    if not daily or len(daily) < 2:
        return None, None
    from ..detectors.sessions import ny_time

    last_day = ny_time(daily[-1].t).date()
    price = daily[-1].c
    if intraday and ny_time(intraday[-1].t).date() > last_day:
        # the daily bar has not rolled over yet (pre-market): measure against the last daily close
        return intraday[-1].c, pct(daily[-1].c, intraday[-1].c)
    if intraday and intraday[-1].t > daily[-1].t:
        price = intraday[-1].c
    return price, pct(daily[-2].c, price)
