"""Rates, yields, volatility and the Fed calendar, from FRED (keyless CSV) and the Federal Reserve's RSS feed."""

import asyncio
from datetime import date, datetime, timezone

from .factor import Factor, clamp
from .feeds import client, get_text, parse_fred_csv, parse_rss

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
SERIES = {
    "DGS10": "10-year Treasury yield",
    "DGS2": "2-year Treasury yield",
    "T10Y2Y": "10y minus 2y curve",
    "DFF": "Fed funds rate",
    "VIXCLS": "VIX (S&P 500 volatility)",
    "DTWEXBGS": "US dollar index (broad)",
}
# FOMC decision days (the second day of each meeting), as scheduled by the Fed for 2026.
# Check https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm for changes and for 2027.
FOMC_DECISIONS = [
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
]
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def fred_link(series: str) -> dict:
    return {"title": f"FRED {series}", "url": f"https://fred.stlouisfed.org/series/{series}"}


def change(points: list[tuple[str, float]], back: int) -> float | None:
    return points[-1][1] - points[-1 - back][1] if len(points) > back else None


def rate_factors(data: dict[str, list[tuple[str, float]]], kind: str) -> list[Factor]:
    """Turn FRED series into scored factors. Rising yields and volatility are headwinds for stocks and crypto."""
    out = []
    growth = kind in ("stock", "crypto")  # long-duration assets feel yields most

    ten = data.get("DGS10")
    if ten:
        d = change(ten, 20)
        if d is not None:
            out.append(Factor(
                "us10y", "Rates and yields", "10-year yield",
                f"{ten[-1][1]:.2f}% ({d * 100:+.0f} bp over 20 trading days). "
                + ("Rising long yields lower what future earnings are worth today, a headwind." if d > 0.05
                   else "Falling long yields support valuations, a tailwind." if d < -0.05 else "Little changed."),
                score=clamp(-d / 0.25), weight=1.5 if growth else 1.2, sources=[fred_link("DGS10")]))

    two = data.get("DGS2")
    if two:
        d = change(two, 20)
        if d is not None:
            out.append(Factor(
                "us2y", "Rates and yields", "2-year yield",
                f"{two[-1][1]:.2f}% ({d * 100:+.0f} bp over 20 trading days). The 2-year tracks where traders expect the Fed rate; "
                + ("it is rising, so the market is pricing fewer cuts." if d > 0.05 else "it is falling, so the market is pricing more cuts." if d < -0.05 else "little changed."),
                score=clamp(-d / 0.3), weight=1.0, sources=[fred_link("DGS2")]))

    curve = data.get("T10Y2Y")
    if curve:
        v = curve[-1][1]
        out.append(Factor(
            "curve", "Rates and yields", "Yield curve (10y - 2y)",
            f"{v:+.2f} pts. " + ("Inverted: markets expect slower growth ahead." if v < 0 else "Positive slope, the normal state."),
            score=0.0, weight=0.0, sources=[fred_link("T10Y2Y")]))

    dff = data.get("DFF")
    if dff:
        d = change(dff, 90)
        detail = f"{dff[-1][1]:.2f}%."
        if d is not None and abs(d) >= 0.1:
            detail += f" {'Cut' if d < 0 else 'Raised'} by {abs(d) * 100:.0f} bp in the last ~3 months, " + ("easier money supports risk assets." if d < 0 else "tighter money weighs on risk assets.")
        out.append(Factor("fedfunds", "Fed", "Fed funds rate", detail,
                          score=clamp(-(d or 0) / 0.5), weight=0.8, sources=[fred_link("DFF")]))

    vix = data.get("VIXCLS")
    if vix:
        v = vix[-1][1]
        score = 0.4 if v < 15 else 0.1 if v < 20 else -0.4 if v < 25 else -0.9
        mood = "calm, buyers in control" if v < 15 else "normal" if v < 20 else "nervous" if v < 25 else "fearful, expect wide swings"
        out.append(Factor("vix", "Rates and yields", "VIX", f"{v:.1f}: {mood}.", score=score, weight=1.0, sources=[fred_link("VIXCLS")]))

    usd = data.get("DTWEXBGS")
    if usd:
        d = change(usd, 20)
        if d is not None:
            pct = d / usd[-1 - 20][1] * 100
            out.append(Factor(
                "usd", "Rates and yields", "US dollar",
                f"{pct:+.1f}% over 20 days. " + ("A stronger dollar tightens conditions and weighs on crypto and multinationals." if pct > 0.5
                                                  else "A weaker dollar eases conditions." if pct < -0.5 else "Little changed."),
                score=clamp(-pct / 2), weight=0.6 if kind != "crypto" else 1.0, sources=[fred_link("DTWEXBGS")]))
    return out


def fomc_factor(today: date, press: list[dict]) -> Factor:
    upcoming = [d for d in FOMC_DECISIONS if d >= today]
    sources = [{"title": "Fed meeting calendar", "url": FOMC_URL}] + [{"title": p["title"], "url": p["url"]} for p in press[:3]]
    latest = f" Latest Fed release: \"{press[0]['title']}\"." if press else ""
    if not upcoming:
        return Factor("fomc", "Fed", "Next Fed decision", "Date not in the built-in calendar; check the Fed's site." + latest, sources=sources)
    nxt = upcoming[0]
    days = (nxt - today).days
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    risk = 1.0 if days <= 1 else 0.6 if days <= 3 else 0.25 if days <= 7 else 0.0
    detail = f"{nxt:%a %d %b}, {when}, statement at 2:00 pm New York time."
    if risk:
        detail += " Price often whipsaws around the decision, so a new entry carries extra risk until it is out."
    return Factor("fomc", "Fed", "Next Fed decision", detail + latest, risk=risk, sources=sources)


async def macro_factors(kind: str, today: date | None = None) -> tuple[list[Factor], list[str]]:
    """Factors plus a list of sources that could not be reached."""
    today = today or datetime.now(timezone.utc).date()
    missing = []
    async with client() as http:
        async def series(sid):
            return sid, parse_fred_csv(await get_text(http, FRED_CSV, id=sid))

        results = await asyncio.gather(*(series(s) for s in SERIES), return_exceptions=True)
        try:
            press = parse_rss(await get_text(http, FED_RSS), limit=5)
        except Exception:
            press = []
            missing.append("Federal Reserve press releases")
    data = {}
    for r in results:
        if isinstance(r, Exception) or not r[1]:
            continue
        data[r[0]] = r[1]
    if len(data) < len(SERIES):
        missing.append("FRED: " + ", ".join(SERIES[s] for s in SERIES if s not in data))
    return rate_factors(data, kind) + [fomc_factor(today, press)], missing
