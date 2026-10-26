# Market Analyser

A market analysis app for day trading US stocks and index ETFs on the news. It scores the day's market-moving news and macro drivers, ranks which sectors are bullish or bearish today, shortlists the names to trade inside them, and times the entry across five timeframes. Charts run day-trader technical detectors on real share prices from Yahoo Finance (crypto still charts from Hyperliquid).

**Analysis only.** The app has no order code and needs no trading keys. Nothing it shows is financial advice.

## The strategy (v0.5)

The full write-up, with every driver, sensitivity and rule, is the strategy doc in the project. The app runs it top down in the **Market today** tab and the **Timeframe Alignment** card beside the chart:

1. **Drivers.** The 10-year yield, oil, the dollar, VIX and copper (Yahoo Finance), plus this week's US economic releases from the free Forex Factory calendar, each turned into a surprise: how far it moved or missed consensus, in typical-day units.
2. **Transmission.** Each surprise goes through the sector sensitivity matrix (`backend/app/strategy/rules.py`), and leaders that made an unusually large move (NVDA, JPM, UNH, XOM and others) pass part of it to their niche. Hyperscalers' spending headlines lift the chip and power niches even when the spender's own shares fall.
3. **Sector board.** About 25 niches (the 11 sectors plus industry ETFs such as SMH, KRE, XBI, ITB, JETS), scored `40% news + 30% relative strength + 15% flow + 15% breadth`. Each row says whether news and price agree (Confirmed), disagree (Sell the news, Bad news priced in) or move on flow alone. A banner flags a risk-to-defensive rotation (tech red while healthcare, staples or utilities lead). The board logs its calls to `data/predictions.json` and shows how often they were right the next session.
4. **Shortlist.** Up to three names in each of the top two bull and bottom two bear niches: beta and correlation to the theme, liquidity, room to move, no earnings within 2 sessions or headlines of their own against the trade, plus bonuses for lagging a leader and leading the niche.
5. **Timeframe Alignment.** Daily and 4H set the bias, 1H and 15m the location, 5m the trigger (the Entry Check on 5m). The verdict is Aligned, Waiting or Conflict, with entry, stop, target and a position size: by default $1000 in with at most 5% ($50) at risk, changeable in the card. Session rules show as warnings: nothing before 9:35 ET, flat by 15:55, no entries 2 minutes before to 5 minutes after a high-impact release. The niche and the alignment also feed the Confidence card.

Longs and shorts both work. Every rule table is plain Python in `backend/app/strategy/` so research can be added as rows.

## The page

The app uses a black and orange theme and splits into four tabs. The market box, timeframe and watchlist at the top work from any tab.

- **Chart**: the chart with Timeframe Alignment, Right now, Entry Check, Confidence, Layers and Latest events beside it.
- **Market today**: the market-wide drivers (yields, oil, dollar, VIX, copper), this week's US economic releases, leaders moving their group, the sector board and the shortlist. Clicking a ticker opens its chart.
- **News**: the news and macro behind the selected market, with Deep research.
- **Glossary**: what BOS, CHoCH, FVG, order blocks, liquidity and the other markings mean and how to use them.

The app remembers which tab was open and returns to it next time.

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

One click loads each of NVDA, TSLA, AAPL, AMD, MSFT, AMZN, META, PLTR, GOOGL, SPY, QQQ, IWM, BTC and SOL (`backend/app/watchlist.py`), and any name on the sector board or shortlist opens with a click. Stocks and ETFs chart the real shares from Yahoo Finance, refreshed every minute. With **Pre and after hours** ticked at the top (the default), pre-market (4am to 9:30am New York) and after-hours (4pm to 8pm) candles show faded, and a dashed orange line marks the latest pre-market or after-hours price, with its change from the last regular close under Price. That line shows on the daily chart too, even though daily candles hold no extended hours. The detectors, Entry Check, VWAP and Timeframe Alignment always read regular-hours candles only, so thin overnight prints don't make fake swings or zones, and they say the same thing with the box on or off. If Yahoo fails, they fall back to Hyperliquid's stock and index perps (`xyz:NVDA`, SPY → `mkts:US500`, QQQ → `mkts:USTECH`, IWM → `mkts:SMALL2000`). Crypto charts live from Hyperliquid.

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

The **Confidence** card blends the two halves for each direction: up to 60 points from the Entry Check, up to 40 from how far the context leans the same way, minus up to 25 for earnings or a Fed decision in the next few days, and capped at 40 when the chart has no setup. Every input is listed on the **News** tab with which way it leans and a link to its source. A source that cannot be reached is named and left out.

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
backend/app/yahoo.py         stock and ETF candles from Yahoo Finance
backend/app/strategy/        the strategy: universe, rule tables, calendar, sector board, shortlist, alignment
backend/app/context/         yields, Fed, earnings, headlines, deep research, confidence score
backend/app/main.py          FastAPI: /api/candles, /api/analysis, /api/context, /api/research,
                             /api/board, /api/shortlist, /api/alignment, serves the frontend
frontend/                    the page: tabs.js, app.js (chart), strategy.js (board and alignment), style.css
                             (TradingView Lightweight Charts 4.2.3, vendored)
```

## Next

A backtest of the sector board's weights on two years of daily data, then the backtester for entries. The news and macro layer above covers the start of phases 5 and 6; next would be fuller fundamentals (valuation, revisions, insider and institutional flows) and positioning data.

Charts by [TradingView](https://www.tradingview.com/) Lightweight Charts™ (Apache 2.0, see `frontend/vendor/LIGHTWEIGHT-CHARTS-LICENSE`).
