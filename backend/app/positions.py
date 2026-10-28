"""The Positions tab: the user's holdings, saved to data/positions.json, and live quotes to value them.

Stocks and ETFs are priced from Yahoo Finance (with pre-market and after-hours trades), crypto from Hyperliquid's
perp marks, falling back to Yahoo's SYMBOL-USD. Read-only like the rest of the app: nothing here places orders.
"""

import asyncio
import json
import math
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, field_validator

from . import yahoo
from .hyperliquid import INFO_URL

FILE = Path(__file__).resolve().parents[2] / "data" / "positions.json"
QUOTE_SECONDS = 15  # quotes are cached this long, so several open tabs don't hammer the sources


class Position(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    kind: str = Field("stock", pattern="^(stock|crypto)$")
    qty: float  # negative for a short
    cost: float = Field(gt=0)  # average price paid per share or coin
    stop: float | None = Field(None, gt=0)  # an open stop order, if any
    note: str = Field("", max_length=200)

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("qty")
    @classmethod
    def nonzero(cls, v: float) -> float:
        if v == 0 or not math.isfinite(v):
            raise ValueError("quantity must be a number other than 0")
        return v


# the Wall Street Survivor portfolio on 28 Oct 2026, used until the user saves their own list
DEFAULTS = [
    Position(symbol="PLD", qty=-50, cost=128.14),
    Position(symbol="UNH", qty=40, cost=377.69, stop=369),
    Position(symbol="NVDA", qty=60, cost=214.86),
    Position(symbol="IBM", qty=50, cost=224.49, stop=217),
    Position(symbol="XLU", qty=150, cost=42.36),
    Position(symbol="SKHY", qty=90, cost=137.16),
    Position(symbol="ONDO", kind="crypto", qty=12500, cost=0.43),
    Position(symbol="SOL", kind="crypto", qty=0.0356, cost=100.59),
]


def load_positions(path: Path = FILE) -> list[Position]:
    try:
        return [Position(**p) for p in json.loads(path.read_text())]
    except FileNotFoundError:
        return list(DEFAULTS)
    except (ValueError, TypeError):
        return list(DEFAULTS)  # a hand-edited file that no longer parses


def save_positions(positions: list[Position], path: Path = FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([p.model_dump() for p in positions], indent=2))
    tmp.replace(path)


# ---- quotes ----

_cache: dict[str, tuple[float, dict]] = {}


def parse_yahoo_quote(data: dict) -> dict:
    """Regular-session price and previous close from Yahoo's chart meta, plus the latest extended-hours trade
    when it is newer than the regular price."""
    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
    except (KeyError, IndexError, TypeError) as exc:
        raise yahoo.YahooError(f"unexpected Yahoo response: {str(data)[:200]}") from exc
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        raise yahoo.YahooError("Yahoo sent no price")
    out = {"price": float(price), "prev_close": float(prev) if prev else None, "ext_price": None, "source": "yahoo"}
    stamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    regular_end = ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("end")
    regular_start = ((meta.get("currentTradingPeriod") or {}).get("regular") or {}).get("start")
    for ts, c in zip(reversed(stamps), reversed(closes)):
        if c is None:
            continue
        if regular_start and regular_end and not regular_start <= ts < regular_end:
            out["ext_price"] = float(c)
        break
    return out


async def _yahoo(http: httpx.AsyncClient, symbol: str) -> dict:
    params = {"interval": "1m", "range": "1d", "includePrePost": "true"}
    try:
        resp = await http.get(yahoo.CHART_URL.format(symbol=symbol), params=params)
    except httpx.HTTPError as exc:
        raise yahoo.YahooError(f"could not reach Yahoo Finance: {exc}") from exc
    if resp.status_code != 200:
        raise yahoo.YahooError(f"Yahoo returned {resp.status_code} for {symbol}")
    return parse_yahoo_quote(resp.json())


def parse_hyperliquid_ctxs(data) -> dict[str, dict]:
    """{coin: quote} from a metaAndAssetCtxs reply: the mark price and the price 24 hours ago."""
    universe, ctxs = data[0]["universe"], data[1]
    out = {}
    for u, c in zip(universe, ctxs):
        mark = c.get("markPx") or c.get("midPx")
        if mark is None:
            continue
        prev = c.get("prevDayPx")
        out[u["name"].upper()] = {"price": float(mark), "prev_close": float(prev) if prev else None,
                                  "ext_price": None, "source": "hyperliquid"}
    return out


async def _hyperliquid(http: httpx.AsyncClient) -> dict[str, dict]:
    try:
        resp = await http.post(INFO_URL, json={"type": "metaAndAssetCtxs"})
        resp.raise_for_status()
        return parse_hyperliquid_ctxs(resp.json())
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
        return {}


def demo_quote(p: Position) -> dict:
    """A steady made-up price near what was paid, for MA_DEMO=1."""
    seed = sum(map(ord, p.symbol))
    drift = math.sin(seed + time.time() / 60) * 0.06
    return {"price": p.cost * (1 + drift), "prev_close": p.cost * (1 + drift * 0.8), "ext_price": None, "source": "demo"}


async def fetch_quotes(positions: list[Position], demo: bool = False) -> dict[str, dict]:
    """{symbol: {price, prev_close, ext_price, source}} or {symbol: {error}} for each distinct holding."""
    if demo:
        return {p.symbol: demo_quote(p) for p in positions}
    now = time.time()
    out, todo = {}, []
    for p in {p.symbol: p for p in positions}.values():
        hit = _cache.get(f"{p.kind}:{p.symbol}")
        if hit and now - hit[0] < QUOTE_SECONDS:
            out[p.symbol] = hit[1]
        else:
            todo.append(p)
    if not todo:
        return out

    async with httpx.AsyncClient(timeout=10, headers=yahoo.HEADERS) as http:
        perps = await _hyperliquid(http) if any(p.kind == "crypto" for p in todo) else {}

        async def one(p: Position) -> tuple[Position, dict]:
            if p.kind == "crypto" and p.symbol in perps:
                return p, perps[p.symbol]
            try:
                return p, await _yahoo(http, f"{p.symbol}-USD" if p.kind == "crypto" else p.symbol)
            except yahoo.YahooError as exc:
                return p, {"error": str(exc)}

        for p, q in await asyncio.gather(*(one(p) for p in todo)):
            if "error" in q:
                old = _cache.get(f"{p.kind}:{p.symbol}")
                q = {**old[1], "stale": True} if old else q  # an old price beats none
            else:
                _cache[f"{p.kind}:{p.symbol}"] = (now, q)
            out[p.symbol] = q
    return out
