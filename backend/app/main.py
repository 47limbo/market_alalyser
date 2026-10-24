"""FastAPI server: candles and analysis over HTTP, plus the chart frontend.

Run:  uvicorn app.main:app --reload          (live Hyperliquid data)
      MA_DEMO=1 uvicorn app.main:app         (offline synthetic data)
"""

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
from .demo import demo_candles
from .hyperliquid import HyperliquidError, fetch_candles
from .models import INTERVAL_MS
from .setups import HIGHER_TIMEFRAME
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
    """A watchlist asset, or an ad hoc one for any other Hyperliquid market."""
    coin = coin.strip()
    asset = find(coin)
    if asset:
        return asset
    name = coin.split(":")[-1].upper()
    kind = "stock" if ":" in coin else "crypto"
    return Asset(name, coin, kind, name, name if kind == "stock" else f"{name}-USD",
                 f"{name} stock" if kind == "stock" else f"{name} crypto price", (name.lower(),))


async def load(coin: str, interval: str, limit: int):
    """Candles and where they came from: Hyperliquid first, Yahoo Finance if that fails."""
    if interval not in INTERVAL_MS:
        raise HTTPException(400, f"interval must be one of {', '.join(INTERVAL_MS)}")
    asset = resolve(coin)
    if DEMO:
        return demo_candles(interval, limit, seed=sum(map(ord, asset.coin))), "demo"
    try:
        data = await fetch_candles(asset.coin, interval, limit)
        if data:
            return data, "hyperliquid"
        error = f"Hyperliquid has no candles for {asset.coin}"
    except HyperliquidError as exc:
        error = str(exc)
    try:
        return await yahoo.fetch_candles(asset.yahoo, interval, limit), "yahoo"
    except yahoo.YahooError as exc:
        raise HTTPException(502, f"{error}; Yahoo fallback also failed: {exc}") from exc


@app.get("/api/config")
async def config():
    return {"version": VERSION, "demo": DEMO, "intervals": list(INTERVAL_MS), "watchlist": [a.to_dict() for a in WATCHLIST]}


@app.get("/api/candles")
async def candles(coin: str = "BTC", interval: str = "15m", limit: int = Query(500, ge=10, le=5000)):
    data, _ = await load(coin, interval, limit)
    return [c.to_dict() for c in data]


@app.get("/api/analysis")
async def analysis(
    coin: str = "BTC",
    interval: str = "15m",
    limit: int = Query(500, ge=30, le=5000),
    swing_lookback: int = Query(3, ge=1, le=10),
    min_rr: float = Query(2.0, gt=0, le=20),
):
    asset = resolve(coin)
    data, source = await load(coin, interval, limit)
    if not data:
        raise HTTPException(404, f"no candles for {coin}")
    htf = HIGHER_TIMEFRAME.get(interval)
    htf_data = (await load(coin, htf, 300))[0] if htf else None
    try:
        report = analyse(data, swing_lookback=swing_lookback, htf_candles=htf_data, min_rr=min_rr)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _setups[f"{asset.ticker}:{interval}"] = report["setups"]
    return {"coin": coin, "interval": interval, "htf_interval": htf, "asset": asset.to_dict(), "source": source,
            "candles": [c.to_dict() for c in data], **report}


@app.get("/api/context")
async def context(coin: str = "BTC", interval: str = "15m"):
    """News, rates, Fed, earnings and politics for the asset, and the confidence of each Entry Check direction."""
    asset = resolve(coin)
    ctx = await get_context(asset, demo=DEMO)
    setups = _setups.get(f"{asset.ticker}:{interval}", [])
    factors = ctx.pop("factors")
    return {**ctx, "factors": [f.to_dict() for f in factors], "confidence": [score_setup(s, factors) for s in setups]}


@app.post("/api/research")
async def research(coin: str = "BTC"):
    """Run Claude deep research on the asset (costs API credit), then return it like /api/context."""
    asset = resolve(coin)
    try:
        await run_research(asset)
    except ResearchUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
