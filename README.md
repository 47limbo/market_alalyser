# Market Analyser

A market analysis app for crypto and stock perpetuals. It loads live candles from Hyperliquid, runs day-trader technical detectors on them and draws the results on the chart.

**Analysis only.** The app has no order code and needs no trading keys. Nothing it shows is financial advice.

## What it does so far

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

| Entry Check (phase 3) | Long and short checklists, entry zone, stop and targets drawn on the chart, and an alert when a setup becomes ready |

The side panel shows current structure, where price sits in the dealing range, the session, ATR, relative volume, and the latest events. Detection rules match Part 2 of the research doc and live in `backend/app/detectors/`.

### Entry Check

`backend/app/setups.py` runs the setup model from Part 3.2 of the research doc for both directions:

1. Higher-timeframe structure agrees (15m checks 4h, 1h checks 1d, and so on)
2. Price in discount for a long, premium for a short
3. Liquidity swept against the trade in the last 40 candles
4. CHoCH or BOS after the sweep
5. The break came with displacement
6. A live fair value gap (or order block) left by the move
7. Price has pulled back into that zone
8. Inside a killzone
9. Volume at least 1.5x average on the break
10. Price on the right side of VWAP
11. Reward to risk at least 2R (stop beyond the sweep plus 0.1 ATR, first target at the next untouched opposing liquidity)

Steps 3 to 6 plus the reward-to-risk rule are required. A setup shows as **forming** while it waits for the pullback and **ready** once price is in the zone; a close beyond the stop cancels it. The other steps add to the score. Change the minimum with `?min_rr=` on `/api/analysis`.

### Watchlist

One click loads each of NVDA, TSLA, AAPL, AMD, MSFT, AMZN, META, PLTR, GOOGL, SPY, QQQ, IWM, BTC and SOL (`backend/app/watchlist.py`). Stocks chart from Hyperliquid's 24/7 stock perps (`xyz:NVDA` and so on), the index ETFs from the index perps (SPY → `mkts:US500`, QQQ → `mkts:USTECH`, IWM → `mkts:SMALL2000`). If a Hyperliquid market fails to load, the chart falls back to the real share or ETF from Yahoo Finance (regular hours only, refreshed every minute).

### News and macro context, and confidence

For the selected asset, `backend/app/context/` gathers, in parallel and cached for 10 minutes:

| Input | Source | Effect |
| --- | --- | --- |
| 10-year and 2-year yields, Fed funds, VIX, dollar | FRED (free, no key) | Rising yields, a rising dollar and a high VIX lean bearish; falling ones lean bullish |
| Next Fed decision and latest Fed releases | Built-in 2026 FOMC calendar, Federal Reserve RSS | Event risk in the 7 days before a decision |
| Asset headlines | Google News and Yahoo Finance RSS, last 2 days | Keyword tone, weighted low, headlines linked |
| Fed, inflation, jobs, tariffs, Congress and White House headlines (crypto: regulation and ETF flows) | Google News RSS | Same |
| Next earnings date, EPS estimates and surprises (stocks) | Yahoo Finance (no key), or Finnhub if you add a free key | Event risk within 7 days of a report; recent beats lean bullish |
| Reported EPS and revenue growth, latest 10-Q, 10-K and earnings 8-K (stocks) | SEC EDGAR filings (no key) | Growth on a year earlier leans bullish |
| Deep research | Claude with web search, optional key | Cited bull and bear case, catalysts, a bias that counts most in the score |

The **Confidence** card blends the two halves for each direction: up to 60 points from the Entry Check, up to 40 from how far the context leans the same way, minus up to 25 for earnings or a Fed decision in the next few days, and capped at 40 when the chart has no setup. Every input is listed under the chart with which way it leans and a link to its source. A source that cannot be reached is named and left out.

#### Optional keys

Everything above works without keys. Only Deep research costs money. Copy `.env.example` to `.env` next to `run.py` and fill in what you want, then restart:

- `FINNHUB_API_KEY`: not needed (Yahoo Finance and SEC filings cover earnings). Free at [finnhub.io](https://finnhub.io/register) if you prefer it as the earnings source.
- `ANTHROPIC_API_KEY`: from [console.anthropic.com](https://console.anthropic.com/), for the Deep research button. It uses `claude-opus-5-5` with web search (up to 10 searches a run) and server-side fallback, so if the model declines a request the API retries it on the model Anthropic recommends. Each run uses API credit. Change the model or effort with `MA_RESEARCH_MODEL` and `MA_RESEARCH_EFFORT`.

## Run it

Needs Python 3.10 or newer ([python.org/downloads](https://www.python.org/downloads/)).

- **Mac:** double-click `start.command`. The first time, macOS may say it is from an unidentified developer: right-click it, choose Open, then Open again.
- **Windows:** double-click `start.bat`.
- **VS Code:** open the folder and press Run on any of `run.py`, `backend/app/main.py`, or pick "Market Analyser" in the Run and Debug panel.
- **Terminal:** `python3 run.py` (add `--demo` for offline demo data).

The first start creates a private environment in `.venv` and installs the packages (about a minute). After that it starts straight away and opens http://localhost:8000 in your browser. Keep the window open while you use the app; press Ctrl+C in it to stop.

Click a ticker in the watchlist, or type any Hyperliquid market (`ETH`, `HYPE`, `xyz:NVDA`), and pick a timeframe. The chart updates live over Hyperliquid's websocket, and the detectors re-run each time a candle closes.

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
backend/app/watchlist.py     the 14 tickers and their chart markets
backend/app/yahoo.py         fallback candles from Yahoo Finance
backend/app/context/         yields, Fed, earnings, headlines, deep research, confidence score
backend/app/main.py          FastAPI: /api/candles, /api/analysis, /api/context, /api/research, serves the frontend
frontend/                    chart page (TradingView Lightweight Charts 4.2.3, vendored)
```

## Next

Phase 4 adds the backtester. The news and macro layer above covers the start of phases 5 and 6; next would be fuller fundamentals (valuation, revisions, insider and institutional flows) and positioning data.

Charts by [TradingView](https://www.tradingview.com/) Lightweight Charts™ (Apache 2.0, see `frontend/vendor/LIGHTWEIGHT-CHARTS-LICENSE`).
