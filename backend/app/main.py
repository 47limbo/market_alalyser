"""FastAPI server: candles and analysis over HTTP, plus the chart frontend.

Run:  uvicorn app.main:app --reload          (live Hyperliquid data)
      MA_DEMO=1 uvicorn app.main:app         (offline synthetic data)
"""

import asyncio
import os
import sys
from pathlib import Path

if __name__ == "__main__" and not __package__:
    # Started by pressing Run on this file: hand over to the launcher, which sets up the environment.
    import runpy

    runpy.run_path(str(Path(__file__).resolve().parents[2] / "run.py"), run_name="__main__")
    sys.exit()

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import VERSION, yahoo
from .analyze import analyse
from .context import ResearchUnavailable, get_context, run_research, score_setup
from .context.factor import Factor
from .demo import demo_candles
from .detectors.sessions import extended_session, regular_hours
from .hyperliquid import HyperliquidError, fetch_candles
from .models import INTERVAL_MS
from .positions import Position, fetch_quotes, load_positions, save_positions
from .setups import HIGHER_TIMEFRAME
from .strategy import get_alignment, get_board, get_shortlist, latest_alignment
from .strategy.universe import name_of, niches_of
from .watchlist import WATCHLIST, Asset, find

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
DEMO = os.environ.get("MA_DEMO", "").strip() == "1"

app = FastAPI(title="Market Analyser", description="Analysis only. This app never places trades.")
_setups: dict[str, list[dict]] = {}


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    # make the browser re-check the page and scripts each load, so an update shows up straight away
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response  # latest Entry Check per market and timeframe, for the confidence score


def resolve(coin: str) -> Asset:
    """A watchlist asset, a stock or ETF from the sector board, or an ad hoc one for any other Hyperliquid market."""
    coin = coin.strip()
    asset = find(coin)
    if asset:
        return asset
    name = coin.split(":")[-1].upper()
    if ":" not in coin and niches_of(name):
        full = name_of(name)
        etf = any(n.etf == name for n in niches_of(name))
        return Asset(name, f"xyz:{name}", "etf" if etf else "stock", full, name, f'"{full}" OR {name} stock',
                     tuple({name.lower(), full.lower()}))
    # a stock held on the Positions tab charts as a stock even when the sector board does not know it
    held = ":" not in coin and any(p.symbol == name and p.kind == "stock" for p in load_positions())
    kind = "stock" if ":" in coin or held else "crypto"
    return Asset(name, f"xyz:{name}" if held else coin, kind, name, name if kind == "stock" else f"{name}-USD",
                 f"{name} stock" if kind == "stock" else f"{name} crypto price", (name.lower(),))


async def load(coin: str, interval: str, limit: int, ext: bool = False):
    """Candles and where they came from. Stocks and ETFs chart the real shares from Yahoo Finance, falling back to
    Hyperliquid's stock perps; crypto is the other way round. For stocks, `ext` keeps pre-market, after-hours and
    overnight bars; without it only regular-session bars come back."""
    if interval not in INTERVAL_MS:
        raise HTTPException(400, f"interval must be one of {', '.join(INTERVAL_MS)}")
    asset = resolve(coin)
    stock = asset.kind != "crypto"

    # Yahoo leaves extended hours out itself; demo data and the perps trade round the clock, so those are fetched
    # deeper and filtered down to the regular session
    trim = stock and not ext
    deep = min(5000, limit * 5) if trim else limit

    def regular_only(data):
        return [c for c in data if regular_hours(c.t, INTERVAL_MS[interval])][-limit:] if trim else data

    if DEMO:
        return regular_only(demo_candles(interval, deep, seed=sum(map(ord, asset.coin)))), "demo"

    async def from_yahoo():
        return await yahoo.fetch_candles(asset.yahoo, interval, limit, prepost=ext or not stock), "yahoo"

    async def from_hyperliquid():
        data = await fetch_candles(asset.coin, interval, deep)
        if not data:
            raise HyperliquidError(f"Hyperliquid has no candles for {asset.coin}")
        return regular_only(data), "hyperliquid"

    order = [from_yahoo, from_hyperliquid] if stock else [from_hyperliquid, from_yahoo]
    if stock and interval not in yahoo.PLAN:
        order.reverse()  # Yahoo has no 3m, 2h, 8h or 12h bars
    errors = []
    for source in order:
        try:
            data, name = await source()
            if data:
                return data, name
            errors.append(f"{name} returned no candles")
        except (HyperliquidError, yahoo.YahooError, ValueError) as exc:
            errors.append(str(exc))
    raise HTTPException(502, "; ".join(errors))


async def extended_quote(coin: str, interval: str, bars) -> dict | None:
    """The latest pre-market or after-hours price against the last regular close, while the regular session is shut.
    Daily bars hold no extended hours, so those read the 5m bars instead."""
    if interval == "1d":
        try:
            bars = (await load(coin, "5m", 200, ext=True))[0]
        except HTTPException:
            return None
    span = INTERVAL_MS["5m" if interval == "1d" else interval]
    if not bars or regular_hours(bars[-1].t, span):
        return None
    last = bars[-1]
    close = next((c.c for c in reversed(bars) if regular_hours(c.t, span)), None)
    return {"t": last.t, "price": last.c, "session": extended_session(last.t), "regular_close": close,
            "change_pct": (last.c / close - 1) * 100 if close else None}


@app.get("/api/config")
async def config():
    return {"version": VERSION, "demo": DEMO, "intervals": list(INTERVAL_MS), "watchlist": [a.to_dict() for a in WATCHLIST]}


@app.get("/api/quotes")
async def quotes():
    """A live price and the day's move for each watchlist ticker, for the chips under the controls."""
    tickers = [Position(symbol=a.ticker, kind="crypto" if a.kind == "crypto" else "stock", qty=1, cost=100)
               for a in WATCHLIST]
    return await fetch_quotes(tickers, DEMO)


@app.get("/api/candles")
async def candles(coin: str = "BTC", interval: str = "15m", limit: int = Query(500, ge=10, le=5000), ext: bool = False):
    data, _ = await load(coin, interval, limit, ext)
    return [c.to_dict() for c in data]


@app.get("/api/analysis")
async def analysis(
    coin: str = "BTC",
    interval: str = "15m",
    limit: int = Query(500, ge=30, le=5000),
    swing_lookback: int = Query(3, ge=1, le=10),
    min_rr: float = Query(2.0, gt=0, le=20),
    ext: bool = False,
):
    asset = resolve(coin)
    ext = ext and asset.kind != "crypto"
    # the detectors and the Entry Check read regular-session bars only (extended hours are thin and gappy), so they
    # match what they say with the box off; the extended-hours bars in the same window are added for the chart
    wide = []
    if ext:
        regular, extended = await asyncio.gather(load(coin, interval, limit),
                                                 load(coin, interval, min(5000, limit * 5), True), return_exceptions=True)
        if isinstance(regular, Exception):
            raise regular
        data, source = regular
        if not isinstance(extended, Exception) and extended[1] == source:  # never mix perp prints into share prices
            wide = extended[0]
    else:
        data, source = await load(coin, interval, limit)
    if not data:
        raise HTTPException(404, f"no candles for {coin}")
    chart = [{**c.to_dict(), "ext": False} for c in data] if ext else [c.to_dict() for c in data]
    if ext:
        times = {c.t for c in data}
        chart += [{**c.to_dict(), "ext": True} for c in wide if c.t >= data[0].t and c.t not in times]
        chart.sort(key=lambda k: k["t"])
    htf = HIGHER_TIMEFRAME.get(interval)
    htf_data = (await load(coin, htf, 300))[0] if htf else None
    try:
        report = analyse(data, swing_lookback=swing_lookback, htf_candles=htf_data, min_rr=min_rr)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _setups[f"{asset.ticker}:{interval}"] = report["setups"]
    return {"coin": coin, "interval": interval, "htf_interval": htf, "asset": asset.to_dict(), "source": source,
            "ext": ext, "extended": await extended_quote(coin, interval, wide) if ext else None,
            "candles": chart, **report}


@app.get("/api/context")
async def context(coin: str = "BTC", interval: str = "15m"):
    """News, rates, Fed, earnings and politics for the asset, and the confidence of each Entry Check direction."""
    asset = resolve(coin)
    ctx = await get_context(asset, demo=DEMO)
    setups = _setups.get(f"{asset.ticker}:{interval}", [])
    factors = ctx.pop("factors") + strategy_factors(asset.ticker)
    return {**ctx, "factors": [f.to_dict() for f in factors], "confidence": [score_setup(s, factors) for s in setups]}


def strategy_factors(ticker: str) -> list[Factor]:
    """The niche and the Timeframe Alignment, as evidence for the confidence score (strategy doc, Stage 5)."""
    a = latest_alignment(ticker)
    if not a:
        return []
    out = []
    sign = 1 if a["direction"] == "long" else -1
    row = a.get("niche")
    if row:
        out.append(Factor("niche", "Strategy", f"Niche: {row['name']} ({row['etf']})",
                          f"{row['label']}, score {row['score']:+.0f} on today's sector board. {row['read']}.",
                          score=max(-1.0, min(1.0, row["score"] / 60)), weight=1.2))
    passed = sum(c["status"] == "pass" for c in a["cards"])
    out.append(Factor("alignment", "Strategy", f"Timeframe Alignment ({a['direction']})",
                      f"{a['verdict']}: {passed} of {len(a['cards'])} timeframes pass. {a['why']}",
                      score=sign * (-0.8 if a["verdict"] == "Conflict" else passed / max(1, len(a["cards"]))), weight=1.5))
    return out


@app.get("/api/board")
async def board():
    """Stages 1 to 3: today's drivers, the market regime and the ranked sector board."""
    try:
        return await get_board(DEMO)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/shortlist")
async def shortlist_():
    """Stage 4: tickers to trade in the strongest and weakest niches."""
    try:
        return await get_shortlist(DEMO)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/alignment")
async def alignment(coin: str = "SPY", direction: str | None = None,
                    amount: float = Query(1000, gt=0), risk_pct: float = Query(5.0, gt=0, le=100)):
    """Stage 5: Daily and 4H bias, 1H and 15m location, 5m trigger, and the sized trade plan."""
    asset = resolve(coin)
    if asset.kind == "crypto":
        raise HTTPException(400, "the strategy covers US stocks and ETFs only")
    return await get_alignment(asset.ticker, load, direction, amount, risk_pct, DEMO)


@app.post("/api/research")
async def research(coin: str = "BTC"):
    """Run Claude deep research on the asset (costs API credit), then return it like /api/context."""
    asset = resolve(coin)
    try:
        await run_research(asset)
    except ResearchUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True}


@app.get("/api/positions")
async def positions():
    """The saved holdings (the Wall Street Survivor portfolio until edited) with a live quote for each."""
    held = load_positions()
    return {"positions": [p.model_dump() for p in held], "quotes": await fetch_quotes(held, DEMO), "demo": DEMO}


@app.put("/api/positions")
async def put_positions(held: list[Position]):
    """Replace the saved holdings with the list the Positions tab sends."""
    save_positions(held)
    return {"positions": [p.model_dump() for p in held], "quotes": await fetch_quotes(held, DEMO), "demo": DEMO}


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
