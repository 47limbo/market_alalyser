"""Earnings date and recent EPS surprises from Finnhub (free key, optional: set FINNHUB_API_KEY)."""

import os
from datetime import date, timedelta

from .factor import Factor, clamp
from .feeds import client

FINNHUB = "https://finnhub.io/api/v1"


def earnings_factors(symbol: str, today: date, calendar: list[dict], history: list[dict]) -> list[Factor]:
    out = []
    link = {"title": f"{symbol} earnings on Finnhub", "url": f"https://finnhub.io/quote/{symbol}"}
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


async def fetch_earnings(symbol: str, today: date) -> tuple[list[Factor], list[str]]:
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        return [Factor("earnings_next", "Earnings", "Earnings",
                       "Add a free FINNHUB_API_KEY to .env for earnings dates and EPS surprises, or run Deep research.")], []
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
