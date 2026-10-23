"""Sessions and killzones in New York time (Part 2.4 of the research doc)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from ..models import Candle

NY = ZoneInfo("America/New_York")

# (name, start hour, end hour) in New York time, end exclusive
KILLZONES = [
    ("Asia", 20, 24),
    ("London", 2, 5),
    ("New York AM", 7, 10),
    ("London close", 10, 12),
]


def ny_time(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=NY)


def killzone_for(ms: int) -> str | None:
    hour = ny_time(ms).hour
    for name, start, end in KILLZONES:
        if start <= hour < end:
            return name
    return None


def session_ranges(candles: list[Candle], name: str) -> list[dict]:
    """High and low of each contiguous run of candles inside the named session."""
    out: list[dict] = []
    run: list[int] = []

    def close_run():
        if run:
            hi = max(run, key=lambda j: candles[j].h)
            lo = min(run, key=lambda j: candles[j].l)
            out.append({
                "session": name,
                "start_index": run[0],
                "end_index": run[-1],
                "high": candles[hi].h,
                "high_index": hi,
                "low": candles[lo].l,
                "low_index": lo,
            })

    for i, k in enumerate(candles):
        if killzone_for(k.t) == name:
            if run and i != run[-1] + 1:
                close_run()
                run = []
            run.append(i)
        elif run:
            close_run()
            run = []
    # a session still running is left out: its range is not final yet
    return out


def killzone_spans(candles: list[Candle]) -> list[dict]:
    """Contiguous candle spans per killzone, for shading on the chart."""
    spans: list[dict] = []
    current: dict | None = None
    for i, k in enumerate(candles):
        kz = killzone_for(k.t)
        if current and (kz != current["name"] or i != current["end_index"] + 1):
            spans.append(current)
            current = None
        if kz:
            if current is None:
                current = {"name": kz, "start_index": i, "end_index": i}
            else:
                current["end_index"] = i
    if current:
        spans.append(current)
    return spans
