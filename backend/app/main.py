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
from .context.factor import Factor
from .demo import demo_candles
from .hyperliquid import HyperliquidError, fetch_candles
from .models import INTERVAL_MS
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
    kind = "stock" if ":" in coin else "crypto"
    return Asset(name, coin, kind, name, name if kind == "stock" else f"{name}-USD",
                 f"{name} stock" if kind == "stock" else f"{name} crypto price", (name.lower(),))


async def load(coin: str, interval: str, limit: int):
    """Candles and where they came from. Stocks and ETFs chart the real shares from Yahoo Finance (with pre-market
    and after-hours), falling back to Hyperliquid's stock perps; crypto is the other way round."""
    if interval not in INTERVAL_MS:
        raise HTTPException(400, f"interval must be one of {', '.join(INTERVAL_MS)}")
    asset = resolve(coin)
    if DEMO:
        return demo_candles(interval, limit, seed=sum(map(ord, asset.coin))), "demo"

    async def from_yahoo():
        return await yahoo.fetch_candles(asset.yahoo, interval, limit), "yahoo"

    async def from_hyperliquid():
        data = await fetch_candles(asset.coin, interval, limit)
        if not data:
            raise HyperliquidError(f"Hyperliquid has no candles for {asset.coin}")
        return data, "hyperliquid"

    order = [from_hyperliquid, from_yahoo] if asset.kind == "crypto" else [from_yahoo, from_hyperliquid]
    if asset.kind != "crypto" and interval not in yahoo.PLAN:
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


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
