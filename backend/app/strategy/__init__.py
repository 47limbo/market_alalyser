"""The news-driven equity strategy from the strategy doc: drivers, sector board, shortlist and Timeframe Alignment.

get_board()      Stages 1 to 3, refreshed every 2 minutes
get_shortlist()  Stage 4, with each candidate's earnings date and own headlines checked
get_alignment()  Stage 5 for one ticker, from five timeframes of candles
"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..analyze import analyse
from ..context.feeds import client
from ..context.news import mentions, search, tone
from ..detectors.sessions import ny_time
from .alignment import TIMEFRAMES, align
from .board import MACRO_SYMBOLS, build_board
from .calendar import Release, demo_releases, fetch_releases
from .demo import DEMO_HEADLINES, demo_daily
from .market import fetch_many
from .rules import LEADERS
from .shortlist import conflict_from, evaluate, shortlist
from .universe import BENCHMARK, NICHES, name_of, niches_of, universe

BOARD_SECONDS = 120
CONFLICT_SECONDS = 1800
LOG = Path(__file__).resolve().parents[3] / "data" / "predictions.json"

_board: tuple[float, dict] | None = None
_board_lock = asyncio.Lock()
_daily: dict = {}
_releases: list[Release] = []
_morning: dict[str, dict[str, int]] = {}  # NY date -> ranks at 10:00 ET, for the rotation detector
_conflicts: dict[str, tuple[float, dict]] = {}
_alignments: dict[str, dict] = {}

__all__ = ["get_board", "get_shortlist", "get_alignment", "latest_alignment"]


def symbols() -> list[str]:
    extra = [ld.ticker for ld in LEADERS]
    return list(dict.fromkeys(universe() + extra + MACRO_SYMBOLS))


async def _leader_headlines(daily: dict, intraday: dict, releases, now_ms) -> dict[str, list[str]]:
    """Spending headlines for hyperscalers that moved, so their capex can be routed to suppliers."""
    board = build_board(daily, intraday, releases, now_ms)
    movers = [ld for ld in LEADERS if ld.capex]
    big = {m["ticker"] for m in board["leaders"]}
    want = [ld for ld in movers if ld.ticker in big] or []
    out: dict[str, list[str]] = {}
    if not want:
        return out
    async with client() as http:
        async def one(ld):
            name = name_of(ld.ticker)
            try:
                items = await search(http, f'"{name}" capex OR "capital expenditure" OR spending')
            except Exception:
                return
            out[ld.ticker] = [i["title"] for i in items if mentions(i["title"], (name.lower(), ld.ticker.lower()))]
        await asyncio.gather(*(one(ld) for ld in want))
    return out


async def _load(demo: bool):
    now_ms = int(time.time() * 1000)
    if demo:
        return demo_daily(), {}, demo_releases(), DEMO_HEADLINES, now_ms, []
    missing = []
    etfs = [BENCHMARK] + [n.etf for n in NICHES] + MACRO_SYMBOLS + [ld.ticker for ld in LEADERS]
    daily_job = fetch_many(symbols(), "daily")
    intraday_job = fetch_many(list(dict.fromkeys(etfs)), "intraday")
    releases_job = fetch_releases()
    daily, intraday, releases = await asyncio.gather(daily_job, intraday_job, releases_job, return_exceptions=True)
    if isinstance(daily, Exception) or not daily:
        raise RuntimeError("Yahoo Finance could not be reached for the sector board")
    if isinstance(intraday, Exception):
        intraday = {}
        missing.append("intraday prices (pre-market moves left out)")
    if isinstance(releases, Exception):
        releases = list(_releases)  # last good copy
        missing.append("economic calendar (Forex Factory feed)")
    gone = [s for s in symbols() if s not in daily]
    if gone:
        missing.append(f"{len(gone)} of {len(symbols())} symbols from Yahoo: {', '.join(gone[:8])}{'…' if len(gone) > 8 else ''}")
    try:
        headlines = await _leader_headlines(daily, intraday, releases, now_ms)
    except Exception:
        headlines = {}
    return daily, intraday, releases, headlines, now_ms, missing


async def get_board(demo: bool = False) -> dict:
    global _board, _daily, _releases
    async with _board_lock:
        if _board and time.time() - _board[0] < BOARD_SECONDS:
            return _board[1]
        daily, intraday, releases, headlines, now_ms, missing = await _load(demo)
        today = ny_time(now_ms).date().isoformat()
        board = build_board(daily, intraday, releases, now_ms, headlines, _morning.get(today))
        t = ny_time(now_ms)
        if today not in _morning and t.weekday() < 5 and t.hour >= 10:
            _morning[today] = {r["etf"]: r["rank"] for r in board["rows"]}
        board["missing"] = missing
        board["demo"] = demo
        board["fetched"] = now_ms
        board["hit_rate"] = record_and_score(board, daily, today, demo)
        _daily, _releases = daily, releases
        _board = (time.time(), board)
        return board


# ---- prediction log (strategy doc, Stage 3d) ----

def _read_log() -> dict:
    try:
        return json.loads(LOG.read_text())
    except (OSError, ValueError):
        return {}


def score_log(log: dict, daily: dict, today: str) -> dict | None:
    """How often a Bull or Bear label was followed by the niche beating or lagging SPY the next session."""
    spy = daily.get(BENCHMARK)
    if not spy:
        return None
    by_day = {ny_time(b.t).date().isoformat(): i for i, b in enumerate(spy)}
    right = total = 0
    last = None
    for day in sorted(d for d in log if d < today)[-10:]:
        i = by_day.get(day)
        if i is None or i + 1 >= len(spy):
            continue
        spy_next = spy[i + 1].c / spy[i].c - 1
        d_right = d_total = 0
        for etf, sign in log[day].items():
            bars = daily.get(etf)
            if not bars or len(bars) != len(spy) or not sign:
                continue
            excess = bars[i + 1].c / bars[i].c - 1 - spy_next
            d_total += 1
            d_right += (excess > 0) == (sign > 0)
        right, total = right + d_right, total + d_total
        if d_total:
            last = {"day": day, "right": d_right, "total": d_total}
    if not total:
        return None
    return {"right": right, "total": total, "rate": round(right / total, 2), "last": last}


def record_and_score(board: dict, daily: dict, today: str, demo: bool) -> dict | None:
    if demo:
        return None
    log = _read_log()
    log[today] = {r["etf"]: (1 if r["score"] >= 20 else -1 if r["score"] <= -20 else 0) for r in board["rows"]}
    cutoff = (date.fromisoformat(today) - timedelta(days=60)).isoformat()
    log = {d: v for d, v in log.items() if d >= cutoff}
    try:
        LOG.parent.mkdir(exist_ok=True)
        LOG.write_text(json.dumps(log))
    except OSError:
        pass
    return score_log(log, daily, today)


# ---- Stage 4 ----

def _earnings_next(ticker: str) -> tuple[str | None, int | None]:
    from ..context.earnings import _yahoo_fetch, yahoo_rows

    today = datetime.now(timezone.utc).date()
    calendar, _ = yahoo_rows(_yahoo_fetch(ticker), today)
    if not calendar:
        return None, None
    nxt = min(calendar, key=lambda c: c["date"])
    days = (date.fromisoformat(nxt["date"]) - today).days
    when = {"bmo": "before the open", "amc": "after the close"}.get(nxt["hour"], "")
    return f"{nxt['date']} {when}".strip(), days


async def _conflict(http, ticker: str, direction: str) -> dict:
    key = f"{ticker}:{direction}"
    hit = _conflicts.get(key)
    if hit and time.time() - hit[0] < CONFLICT_SECONDS:
        return hit[1]
    try:
        nxt, days = await asyncio.wait_for(asyncio.to_thread(_earnings_next, ticker), timeout=20)
    except Exception:
        nxt, days = None, None
    try:
        name = name_of(ticker)
        items = await search(http, f'"{name}" OR {ticker} stock')
        tones = [tone(i["title"]) for i in items if mentions(i["title"], (name.lower(), ticker.lower()))]
    except Exception:
        tones = []
    got = conflict_from(direction, nxt, days, tones)
    _conflicts[key] = (time.time(), got)
    return got


async def get_shortlist(demo: bool = False) -> dict:
    board = await get_board(demo)
    first = shortlist(board, _daily)
    conflicts: dict[str, dict] = {}
    if demo:
        conflicts = {c["ticker"]: conflict_from(g["direction"], "in 9 days", 9, []) for g in first for c in g["candidates"]}
    else:
        wanted = {(c["ticker"], g["direction"]) for g in first for c in g["candidates"]}
        async with client() as http:
            got = await asyncio.gather(*(_conflict(http, t, d) for t, d in wanted))
        conflicts = {t: g for (t, _), g in zip(wanted, got)}
    return {"groups": shortlist(board, _daily, conflicts), "regime_label": board["regime_label"], "fetched": board["fetched"]}


# ---- Stage 5 ----

def niche_for(ticker: str, board: dict) -> dict | None:
    """The board row of the ticker's niche that leans hardest, so a stock in several niches follows the strongest."""
    rows = {r["etf"]: r for r in board["rows"]}
    mine = [rows[n.etf] for n in niches_of(ticker) if n.etf in rows]
    if ticker == BENCHMARK or not mine:
        return None
    return max(mine, key=lambda r: abs(r["score"]))


async def get_alignment(ticker: str, load, direction: str | None = None, amount: float = 1000, risk_pct: float = 5.0,
                        demo: bool = False) -> dict:
    """`load(ticker, interval, limit)` returns (candles, source): the same loader the chart uses."""
    try:
        board = await get_board(demo)
    except Exception:
        board = {"rows": [], "bull": [], "bear": [], "leaders": []}
    row = niche_for(ticker, board)

    got = await asyncio.gather(*(load(ticker, tf, 250 if tf == "1d" else 300) for tf in TIMEFRAMES), return_exceptions=True)
    candles = {tf: x[0] for tf, x in zip(TIMEFRAMES, got) if not isinstance(x, Exception) and x[0]}
    reports = {}
    for tf, bars in candles.items():
        try:
            # the 5m trigger checks the 1H trend, as the Entry Check does
            reports[tf] = analyse(bars, htf_candles=candles.get("1h") if tf == "5m" else None) | {"candles": [c.to_dict() for c in bars]}
        except ValueError:
            continue

    if direction not in ("long", "short"):
        if row and abs(row["score"]) >= 20:
            direction = "long" if row["score"] > 0 else "short"
        else:
            direction = "short" if reports.get("1d", {}).get("trend") == "bearish" else "long"

    candidate = None
    if row and _daily:
        cached = _conflicts.get(f"{ticker}:{direction}")
        c = evaluate(ticker, row["etf"], direction, _daily, board.get("leaders", []), cached[1] if cached else None)
        candidate = c.to_dict() if c else None

    result = align(reports, direction, int(time.time() * 1000), _releases, amount, risk_pct, row, candidate)
    result["ticker"] = ticker
    result["missing"] = [tf for tf in TIMEFRAMES if tf not in reports]
    result["candidate"] = candidate
    _alignments[ticker] = {"at": time.time(), **result}
    return result


def latest_alignment(ticker: str, max_age: float = 900) -> dict | None:
    a = _alignments.get(ticker)
    return a if a and time.time() - a["at"] < max_age else None
