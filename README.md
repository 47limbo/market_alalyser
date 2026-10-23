# Market Analyser

A market analysis app for crypto and stock perpetuals. It loads live candles from Hyperliquid, runs day-trader technical detectors on them and draws the results on the chart.

**Analysis only.** The app has no order code and needs no trading keys. Nothing it shows is financial advice.

## What phase 1 and 2 include

| Detector | What you see on the chart |
| --- | --- |
| Swings, BOS, CHoCH, displacement | Lines from the broken swing to the break candle, labelled BOS or CHoCH (dashed) |
| Fair value gaps | Green or red boxes until filled or closed through (inverted) |
| Order blocks and breakers | Blue (bullish) or orange (bearish) boxes from the block candle to now |
| Resting liquidity | Dotted lines at unswept swing highs and lows (BSL, SSL), equal highs/lows (EQH, EQL), previous day high/low (PDH, PDL), Asia session high/low |
| Liquidity sweeps | Arrows where price took a level and closed back inside within 3 candles |
| Premium / discount and OTE | Shaded halves of the current dealing range, 50% line and the 62 to 79% OTE box |
| Killzones | Shaded Asia, London, New York AM and London close windows (New York time) |
| VWAP | Daily VWAP with 1 and 2 standard deviation bands |
| Volume profile | Volume by price on the right edge, with point of control and value area |

The side panel shows current structure, where price sits in the dealing range, the session, ATR, relative volume, and the latest events. Detection rules match Part 2 of the research doc and live in `backend/app/detectors/`.

## Run it

Needs Python 3.11 or newer.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000. Type a market (`BTC`, `ETH`, `SOL`, or a stock perp such as `xyz:NVDA`) and pick a timeframe. The chart updates live over Hyperliquid's websocket, and the detectors re-run each time a candle closes.

No internet? Start with `MA_DEMO=1 uvicorn app.main:app` to use synthetic candles.

## Tests

```bash
cd backend && python -m pytest -q
```

The tests build small hand-made candle sequences and check each rule, plus a check that the detectors never use future candles.

## Layout

```
backend/app/hyperliquid.py   read-only candle client (public /info endpoint)
backend/app/detectors/       structure, zones, liquidity, sessions, volume, indicators
backend/app/analyze.py       runs all detectors and returns one report
backend/app/main.py          FastAPI: /api/candles, /api/analysis, serves the frontend
frontend/                    chart page (TradingView Lightweight Charts 4.2.3, vendored)
```

## Next

Phase 3 adds the Entry Check (setup scoring with stop, targets and reward to risk) and alerts. Phase 4 adds the backtester, phase 5 the fundamental and macro Bias Score, and phase 6 the AI analyst brief.

Charts by [TradingView](https://www.tradingview.com/) Lightweight Charts™ (Apache 2.0, see `frontend/vendor/LIGHTWEIGHT-CHARTS-LICENSE`).
