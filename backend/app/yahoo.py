"""Candles from Yahoo Finance's public chart endpoint: the main chart for stocks and ETFs, and the data behind
the sector board.

Intraday bars include pre-market and after-hours trading unless `prepost` is off. Yahoo has no 4h bars, so 4h is built from 1h.
"""

import httpx

from .models import Candle

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) MarketAnalyser/1.0"}
# Yahoo's interval name and the longest range it serves at that interval
PLAN = {
    "1m": ("1m", "7d"), "5m": ("5m", "60d"), "15m": ("15m", "60d"), "30m": ("30m", "60d"),
    "1h": ("60m", "730d"), "4h": ("60m", "730d"), "1d": ("1d", "10y"),
}


class YahooError(RuntimeError):
    pass


def parse_chart(data: dict) -> list[Candle]:
    try:
        result = data["chart"]["result"][0]
        stamps = result["timestamp"]
        q = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise YahooError(f"unexpected Yahoo response: {str(data)[:200]}") from exc
    out = []
    for i, ts in enumerate(stamps):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue  # Yahoo leaves gaps as nulls
        out.append(Candle(t=int(ts) * 1000, o=float(o), h=float(h), l=float(l), c=float(c), v=float(v or 0)))
    return out


def resample(candles: list[Candle], ms: int) -> list[Candle]:
    buckets: dict[int, list[Candle]] = {}
    for k in candles:
        buckets.setdefault(k.t - k.t % ms, []).append(k)
    return [
        Candle(t=t, o=g[0].o, h=max(k.h for k in g), l=min(k.l for k in g), c=g[-1].c, v=sum(k.v for k in g))
        for t, g in sorted(buckets.items())
    ]


async def fetch_candles(symbol: str, interval: str, limit: int = 500, client: httpx.AsyncClient | None = None,
                        rng: str | None = None, prepost: bool = True) -> list[Candle]:
    if interval not in PLAN:
        raise ValueError(f"unsupported interval {interval!r}")
    yahoo_interval, longest = PLAN[interval]
    params = {"interval": yahoo_interval, "range": rng or longest}
    if interval != "1d" and prepost:
        params["includePrePost"] = "true"
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=15, headers=HEADERS)
    try:
        resp = await client.get(CHART_URL.format(symbol=symbol), params=params)
        if resp.status_code != 200:
            raise YahooError(f"Yahoo returned {resp.status_code}")
        candles = parse_chart(resp.json())
    except httpx.HTTPError as exc:
        raise YahooError(f"could not reach Yahoo Finance: {exc}") from exc
    finally:
        if own_client:
            await client.aclose()
    if interval == "4h":
        candles = resample(candles, 4 * 3_600_000)
    return candles[-limit:]
