"""Read-only Hyperliquid market data client.

Uses the public /info endpoint only. There is deliberately no exchange or order code here:
the app analyses markets and never trades.
"""

import time

import httpx

from .models import INTERVAL_MS, Candle

INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_CANDLES = 5000  # Hyperliquid serves at most the most recent 5000 candles per interval


class HyperliquidError(RuntimeError):
    pass


def _parse(raw: dict) -> Candle:
    return Candle(
        t=int(raw["t"]),
        o=float(raw["o"]),
        h=float(raw["h"]),
        l=float(raw["l"]),
        c=float(raw["c"]),
        v=float(raw["v"]),
    )


async def fetch_candles(coin: str, interval: str, limit: int = 500, client: httpx.AsyncClient | None = None) -> list[Candle]:
    """Most recent `limit` candles for a coin, e.g. "BTC", or a HIP-3 stock perp such as "xyz:NVDA"."""
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}")
    limit = max(1, min(limit, MAX_CANDLES))
    end = int(time.time() * 1000)
    start = end - limit * INTERVAL_MS[interval]
    body = {"type": "candleSnapshot", "req": {"coin": coin, "interval": interval, "startTime": start, "endTime": end}}

    own_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(INFO_URL, json=body)
        if resp.status_code != 200:
            raise HyperliquidError(f"Hyperliquid returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
    except httpx.HTTPError as exc:
        raise HyperliquidError(f"could not reach Hyperliquid: {exc}") from exc
    finally:
        if own_client:
            await client.aclose()

    if not isinstance(data, list):
        raise HyperliquidError(f"unexpected response: {str(data)[:200]}")
    return [_parse(x) for x in data][-limit:]
