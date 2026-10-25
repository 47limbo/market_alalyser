"""Stage 1: the week's US economic releases and how far each one surprised.

Source: the free, keyless Forex Factory weekly calendar feed (consensus and previous for every release; it adds
the actual once it is out on most weeks). A release is scored as

    surprise = (actual - consensus) / the typical miss for that release

then signed for stocks' driver columns: hot inflation (cpi), strong economy (jobs), hawkish Fed (y10).
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from ..context.feeds import client

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FEED_PAGE = "https://www.forexfactory.com/calendar"

# title pattern -> (driver column, typical miss in the release's own units, +1 if a higher number means that
# driver rises, -1 if it means it falls). Checked in order, first match wins.
RELEASES = [
    (r"core cpi", "cpi", 0.1, 1),
    (r"\bcpi\b", "cpi", 0.1, 1),
    (r"core pce", "cpi", 0.1, 1),
    (r"\bpce\b", "cpi", 0.1, 1),
    (r"core ppi", "cpi", 0.2, 1),
    (r"\bppi\b", "cpi", 0.2, 1),
    (r"average hourly earnings|employment cost", "cpi", 0.1, 1),
    (r"inflation expectations", "cpi", 0.2, 1),
    (r"non-farm|nonfarm", "jobs", 50, 1),
    (r"adp", "jobs", 40, 1),
    (r"unemployment rate", "jobs", 0.1, -1),
    (r"unemployment claims|jobless claims", "jobs", 15, -1),
    (r"jolts", "jobs", 0.3, 1),
    (r"ism|pmi", "jobs", 1.5, 1),
    (r"retail sales", "jobs", 0.4, 1),
    (r"\bgdp\b", "jobs", 0.5, 1),
    (r"durable goods", "jobs", 1.5, 1),
    (r"consumer sentiment|consumer confidence", "jobs", 2.5, 1),
    (r"housing starts|building permits|home sales", "jobs", 0.05, 1),
    (r"federal funds rate|fomc", "y10", 0.25, 1),
]
_RELEASES = [(re.compile(p, re.I), d, s, sign) for p, d, s, sign in RELEASES]
_NUM = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*([%KMBT]?)\s*$", re.I)
_SCALE = {"": 1, "%": 1, "K": 1, "M": 1e3, "B": 1e6, "T": 1e9}  # K units, so payrolls compare in thousands


@dataclass
class Release:
    title: str
    time: int  # ms since epoch
    impact: str  # High, Medium, Low
    consensus: str
    previous: str
    actual: str
    driver: str | None
    surprise: float | None  # signed for the driver column, in typical misses
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def number(text: str | None) -> float | None:
    """'0.3%' -> 0.3, '180K' -> 180, '1.2M' -> 1200 (thousands), '' -> None."""
    m = _NUM.match(text or "")
    if not m:
        return None
    return float(m.group(1)) * _SCALE[m.group(2).upper()]


def classify(title: str) -> tuple[str, float, int] | None:
    for pattern, driver, scale, sign in _RELEASES:
        if pattern.search(title):
            return driver, scale, sign
    return None


def describe(title: str, driver: str | None, surprise: float | None) -> str:
    if surprise is None:
        return "Not out yet." if driver else "Not scored."
    size = "far " if abs(surprise) >= 2 else ""
    if abs(surprise) < 0.5:
        return "In line with consensus."
    word = {"cpi": ("hotter", "cooler"), "jobs": ("stronger", "weaker"), "y10": ("more hawkish", "more dovish")}[driver]
    return f"{size}{word[0] if surprise > 0 else word[1]} than expected ({surprise:+.1f} typical misses)."


def parse_feed(rows: list[dict]) -> list[Release]:
    out = []
    for r in rows:
        if r.get("country") != "USD" or r.get("impact") not in ("High", "Medium"):
            continue
        try:
            when = datetime.fromisoformat(r["date"])
        except (KeyError, ValueError):
            continue
        title = r.get("title", "")
        kind = classify(title)
        driver = kind[0] if kind else None
        actual, consensus = number(r.get("actual")), number(r.get("forecast"))
        surprise = None
        if kind and actual is not None and consensus is not None:
            surprise = round(max(-4.0, min(4.0, (actual - consensus) / kind[1] * kind[2])), 2)
        out.append(Release(title, int(when.timestamp() * 1000), r["impact"], r.get("forecast") or "",
                           r.get("previous") or "", r.get("actual") or "", driver, surprise, describe(title, driver, surprise)))
    return sorted(out, key=lambda x: x.time)


def driver_surprises(releases: list[Release], now_ms: int, days: int = 3) -> dict[str, float]:
    """The strongest recent surprise per driver column, fading to nothing over `days`."""
    out: dict[str, float] = {}
    for r in releases:
        if r.surprise is None or not r.driver or r.time > now_ms:
            continue
        age = (now_ms - r.time) / 86_400_000
        if age > days:
            continue
        weight = (1.0 if r.impact == "High" else 0.5) * (1 - age / days)
        v = r.surprise * weight
        if abs(v) > abs(out.get(r.driver, 0)):
            out[r.driver] = round(v, 2)
    return out


def blackout(releases: list[Release], now_ms: int) -> Release | None:
    """A high-impact release within 2 minutes ahead or 5 minutes behind: no new entries (strategy doc, Stage 5)."""
    for r in releases:
        if r.impact == "High" and r.time - 2 * 60_000 <= now_ms <= r.time + 5 * 60_000:
            return r
    return None


def upcoming_high(releases: list[Release], now_ms: int, hours: int = 36) -> list[Release]:
    return [r for r in releases if r.impact == "High" and now_ms <= r.time <= now_ms + hours * 3_600_000]


async def fetch_releases() -> list[Release]:
    async with client() as http:
        resp = await http.get(FEED)
        resp.raise_for_status()
        return parse_feed(resp.json())


def demo_releases(now: datetime | None = None) -> list[Release]:
    now = now or datetime.now(timezone.utc)
    day = now.replace(hour=12, minute=30, second=0, microsecond=0)
    rows = [
        {"title": "Core CPI m/m", "date": (day - timedelta(days=1)).isoformat(), "impact": "High", "forecast": "0.3%", "previous": "0.3%", "actual": "0.2%"},
        {"title": "CPI y/y", "date": (day - timedelta(days=1)).isoformat(), "impact": "High", "forecast": "2.9%", "previous": "3.0%", "actual": "2.8%"},
        {"title": "Unemployment Claims", "date": day.isoformat(), "impact": "High", "forecast": "225K", "previous": "231K", "actual": "219K"},
        {"title": "Crude Oil Inventories", "date": day.isoformat(), "impact": "Medium", "forecast": "-1.1M", "previous": "2.3M", "actual": ""},
        {"title": "Retail Sales m/m", "date": (day + timedelta(days=1)).isoformat(), "impact": "High", "forecast": "0.4%", "previous": "0.6%", "actual": ""},
    ]
    return parse_feed([dict(r, country="USD") for r in rows])
