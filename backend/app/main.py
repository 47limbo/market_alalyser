"""FastAPI server: candles and analysis over HTTP, plus the chart frontend.

Run:  uvicorn app.main:app --reload          (live Hyperliquid data)
      MA_DEMO=1 uvicorn app.main:app         (offline synthetic data)
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analyze import analyse
from .demo import demo_candles
from .hyperliquid import HyperliquidError, fetch_candles
from .models import INTERVAL_MS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
DEMO = os.environ.get("MA_DEMO") == "1"

app = FastAPI(title="Market Analyser", description="Analysis only. This app never places trades.")


async def load(coin: str, interval: str, limit: int):
    if interval not in INTERVAL_MS:
        raise HTTPException(400, f"interval must be one of {', '.join(INTERVAL_MS)}")
    if DEMO:
        return demo_candles(interval, limit, seed=sum(map(ord, coin)))
    try:
        return await fetch_candles(coin, interval, limit)
    except HyperliquidError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/config")
async def config():
    return {"demo": DEMO, "intervals": list(INTERVAL_MS)}


@app.get("/api/candles")
async def candles(coin: str = "BTC", interval: str = "15m", limit: int = Query(500, ge=10, le=5000)):
    return [c.to_dict() for c in await load(coin, interval, limit)]


@app.get("/api/analysis")
async def analysis(
    coin: str = "BTC",
    interval: str = "15m",
    limit: int = Query(500, ge=30, le=5000),
    swing_lookback: int = Query(3, ge=1, le=10),
):
    data = await load(coin, interval, limit)
    if not data:
        raise HTTPException(404, f"no candles for {coin}")
    try:
        report = analyse(data, swing_lookback=swing_lookback)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"coin": coin, "interval": interval, "candles": [c.to_dict() for c in data], **report}


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
