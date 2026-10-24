"""Earnings date and recent EPS surprises.

Keyless by default: Yahoo Finance's earnings calendar (through the yfinance package). If you set a free
FINNHUB_API_KEY it is used instead. Reported results straight from SEC filings are in sec.py.
"""

import asyncio
import math
import os
from datetime import date, timedelta

from .factor import Factor, clamp
from .feeds import client

FINNHUB = "https://finnhub.io/api/v1"


def earnings_factors(symbol: str, today: date, calendar: list[dict], history: list[dict], link: dict | None = None) -> list[Factor]:
    """calendar: upcoming {date, hour (bmo/amc), epsEstimate}; history: newest first {actual, estimate, period}."""
    out = []
    link = link or {"title": f"{symbol} earnings on Finnhub", "url": f"https://finnhub.io/quote/{symbol}"}
    upcoming = sorted((c for c in calendar if c.get("date") and c["date"] >= today.isoformat()), key=lambda c: c["date"])
    if upcoming:
        nxt = upcoming[0]
        days = (date.fromisoformat(nxt["date"]) - today).days
        timing = {"bmo": "before the open", "amc": "after the close"}.get(nxt.get("hour"), "")
        est = f", EPS estimate {nxt['epsEstimate']:.2f}" if nxt.get("epsEstimate") is not None else ""
        risk = 1.0 if days <= 1 else 0.7 if days <= 3 else 0.35 if days <= 7 else 0.0
        detail = f"{nxt['date']} {timing}".strip() + f" ({days} days){est}."
        if risk:
            detail += " Shares can gap well past any stop on the report, so treat a new entry as higher risk until it is out."
        out.append(Factor("earnings_next", "Earnings", "Next earnings", detail, risk=risk, sources=[link]))
    else:
        out.append(Factor("earnings_next", "Earnings", "Next earnings", "No report in the next 60 days.", sources=[link]))

    beats = [h for h in history if h.get("actual") is not None and h.get("estimate")]
    if beats:
        last = beats[0]
        surprise = (last["actual"] - last["estimate"]) / abs(last["estimate"]) * 100
        streak = sum(h["actual"] > h["estimate"] for h in beats[:4])
        out.append(Factor(
            "eps_surprise", "Earnings", "Last EPS result",
            f"{last.get('period', '')}: EPS {last['actual']:.2f} vs {last['estimate']:.2f} expected ({surprise:+.1f}%). "
            f"Beat {streak} of the last {min(4, len(beats))} quarters. Stocks that beat tend to drift up for weeks after.",
            score=clamp(surprise / 10) * 0.7 + (streak / min(4, len(beats)) - 0.5) * 0.6, weight=1.0, sources=[link]))
    return out


def _num(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def yahoo_rows(rows: list[tuple], today: date) -> tuple[list[dict], list[dict]]:
    """(datetime in New York time, EPS estimate, reported EPS) rows into calendar and newest-first history."""
    calendar, history = [], []
    for when, estimate, actual in sorted(rows, key=lambda r: r[0], reverse=True):
        day = when.date()
        if actual is not None:
            history.append({"actual": actual, "estimate": estimate, "period": f"Reported {day:%d %b %Y}"})
        elif day >= today:
            calendar.append({"date": day.isoformat(), "hour": "bmo" if when.hour < 12 else "amc", "epsEstimate": estimate})
    return calendar, history


def _yahoo_fetch(symbol: str) -> list[tuple]:
    import yfinance  # handles Yahoo's cookie handshake, which plain requests no longer pass

    df = yfinance.Ticker(symbol).get_earnings_dates(limit=12)
    if df is None or df.empty:
        return []
    return [(ts.to_pydatetime(), _num(r.get("EPS Estimate")), _num(r.get("Reported EPS"))) for ts, r in df.iterrows()]


async def yahoo_earnings(symbol: str, today: date) -> list[Factor]:
    rows = await asyncio.wait_for(asyncio.to_thread(_yahoo_fetch, symbol), timeout=20)
    calendar, history = yahoo_rows(rows, today)
    link = {"title": f"{symbol} earnings on Yahoo Finance", "url": f"https://finance.yahoo.com/quote/{symbol}/analysis/"}
    return earnings_factors(symbol, today, calendar, history, link)


async def fetch_earnings(symbol: str, today: date) -> tuple[list[Factor], list[str]]:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        try:
            return await yahoo_earnings(symbol, today), []
        except Exception:
            return [], ["Yahoo Finance earnings calendar"]
    try:
        async with client() as http:
            cal = await http.get(f"{FINNHUB}/calendar/earnings", params={
                "symbol": symbol, "from": today.isoformat(), "to": (today + timedelta(days=60)).isoformat(), "token": key})
            hist = await http.get(f"{FINNHUB}/stock/earnings", params={"symbol": symbol, "limit": 4, "token": key})
            cal.raise_for_status()
            hist.raise_for_status()
        return earnings_factors(symbol, today, cal.json().get("earningsCalendar", []), hist.json()), []
    except Exception:
        return [], ["Finnhub earnings"]
