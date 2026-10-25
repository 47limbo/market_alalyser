"""Stages 1 to 3 of the strategy: today's drivers, the market regime and the ranked sector board.

    Score = 0.40 news impulse + 0.30 relative strength + 0.15 flow + 0.15 breadth     (each -100 to +100)

News impulse is every driver's z-score times the niche's sensitivity (rules.SENSITIVITY), plus spillover from
leaders that made a big move. Relative strength, flow and breadth come from prices, so a niche only scores high
when the news and the tape agree. Everything here is a pure function of bars and releases; board_snapshot()
fetches them.
"""

import math
from dataclasses import asdict, dataclass, field

from ..detectors.sessions import ny_time
from ..models import Candle
from . import market as mk
from .calendar import Release, driver_surprises, upcoming_high
from .rules import (CAPEX_WORDS, DRIVER_WORDS, DRIVERS, LEADERS, REGIME_NOTES, REGIMES, SENSITIVITY, SPILLOVER, detect_regime,
                    label, read)
from .universe import BENCHMARK, NICHES, Niche

WEIGHTS = {"news": 0.40, "rs": 0.30, "flow": 0.15, "breadth": 0.15}
# Yahoo symbol and the size of a typical daily move, to turn today's change into a z-score
MACRO = {
    "y10": ("^TNX", 6.0),  # basis points
    "oil": ("CL=F", 2.0),  # percent
    "usd": ("DX-Y.NYB", 0.4),
    "vix": ("^VIX", 7.0),
    "copper": ("HG=F", 1.5),
}
EXTRA_MACRO = {"gold": "GC=F", "hy": "HYG"}
MACRO_SYMBOLS = [s for s, _ in MACRO.values()] + list(EXTRA_MACRO.values())
LEADER_MOVE_Z = 2.0  # a leader's excess move this many standard deviations counts as news
DEFENSIVE = [n.etf for n in NICHES if n.defensive]


@dataclass
class Driver:
    key: str
    label: str
    value: str
    change: str
    z: float  # signed: + means the driver rose
    source: str
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Row:
    etf: str
    name: str
    score: float
    label: str
    news: float
    rs: float
    flow: float
    breadth: float
    today: float | None  # % move today
    excess: float | None  # % move today minus SPY's
    read: str
    action: str
    reasons: list[str] = field(default_factory=list)
    next_session: str = ""
    rank: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def squash(x: float, scale: float) -> float:
    return round(100 * math.tanh(x / scale), 1)


def clamp(x: float, lim: float = 3.0) -> float:
    return max(-lim, min(lim, x))


# ---- Stage 1: drivers ----

def macro_drivers(daily: dict[str, list[Candle]], intraday: dict[str, list[Candle]],
                  releases: list[Release], now_ms: int) -> tuple[dict[str, float], list[Driver], dict]:
    """z-score per sensitivity column, the driver chips to show, and the inputs the regime check needs."""
    z: dict[str, float] = {}
    chips: list[Driver] = []
    facts: dict = {}
    for key, (sym, typical) in MACRO.items():
        bars = daily.get(sym)
        if not bars or len(bars) < 6:
            continue
        price, move = mk.today_move(bars, intraday.get(sym))
        if price is None:
            continue
        prev = price / (1 + move / 100)
        if key == "y10":
            change = (price - prev) * 100  # yield points to basis points
            five = (price - bars[-6].c) * 100
            facts["y10_5d"] = five
            chips.append(Driver(key, DRIVERS[key], f"{price:.2f}%", f"{change:+.0f} bp today, {five:+.0f} bp 5d", 0, sym, _yahoo(sym)))
        else:
            change = move
            five = mk.ret(bars, 5) or 0
            facts[f"{key}_5d"] = five
            value = f"{price:.2f}" if key != "vix" else f"{price:.1f}"
            chips.append(Driver(key, DRIVERS[key], value, f"{change:+.1f}% today, {five:+.1f}% 5d", 0, sym, _yahoo(sym)))
        if key == "vix":
            facts["vix"], facts["vix_1d"] = price, move
        z[key] = round(clamp(change / typical), 2)
        chips[-1].z = z[key]

    spy = daily.get(BENCHMARK)
    if spy and len(spy) >= 20:
        facts["spy_above_20d"] = spy[-1].c > mk.sma(spy, 20)

    surprises = driver_surprises(releases, now_ms)
    facts["hot_inflation"] = surprises.get("cpi", 0)
    for key, s in surprises.items():
        z[key] = round(clamp(z.get(key, 0) + s), 2)
    return z, chips, facts


def _yahoo(sym: str) -> str:
    return f"https://finance.yahoo.com/quote/{sym}"


def read_for_regime(z: dict[str, float], regime: str) -> dict[str, float]:
    """In an inflation scare a strong economy reads as more inflation, so the jobs surprise moves to the cpi column."""
    if regime == "inflation" and z.get("jobs"):
        z = dict(z)
        z["cpi"] = clamp(z.get("cpi", 0) + z.pop("jobs"))
    return z


# ---- Stage 2: leader spillover ----

def leader_moves(daily: dict[str, list[Candle]], intraday: dict[str, list[Candle]], headlines: dict[str, list[str]]) -> list[dict]:
    """Leaders whose move today, net of SPY, is unusually large, and whether their news talks about spending."""
    spy = daily.get(BENCHMARK)
    if not spy:
        return []
    _, spy_today = mk.today_move(spy, intraday.get(BENCHMARK))
    spy_rets = mk.daily_returns(spy)[-60:]
    out = []
    for ld in LEADERS:
        bars = daily.get(ld.ticker)
        if not bars or len(bars) < 30 or spy_today is None:
            continue
        _, today = mk.today_move(bars, intraday.get(ld.ticker))
        if today is None:
            continue
        excess_hist = [a - b for a, b in zip(mk.daily_returns(bars)[-60:], spy_rets)]
        sd = mk.stdev(excess_hist) or 1.0
        zz = (today - spy_today) / sd
        capex = any(w in h.lower() for h in headlines.get(ld.ticker, []) for w in CAPEX_WORDS) if ld.capex else False
        if abs(zz) >= LEADER_MOVE_Z or capex:
            out.append({"ticker": ld.ticker, "today": round(today, 2), "excess": round(today - spy_today, 2),
                        "z": round(zz, 2), "niches": list(ld.niches), "peers": list(ld.peers), "why": ld.why,
                        "capex": capex, "capex_niches": list(ld.capex) if capex else []})
    return out


# ---- Stage 3: the board ----

def news_impulse(niche: Niche, z: dict[str, float], leaders: list[dict]) -> tuple[float, list[str]]:
    sens = SENSITIVITY.get(niche.profile, {})
    raw, parts = 0.0, []
    for key, value in z.items():
        s = sens.get(key, 0)
        if not s or not value:
            continue
        c = s / 2 * value
        raw += c
        parts.append((abs(c), f"{DRIVER_WORDS[key][0 if value > 0 else 1]} ({value:+.1f}σ): {'tailwind' if c > 0 else 'headwind'}"))
    for ld in leaders:
        if niche.etf in ld["niches"] and abs(ld["z"]) >= LEADER_MOVE_Z:
            c = SPILLOVER * clamp(ld["z"])
            raw += c
            parts.append((abs(c), f"{ld['ticker']} {ld['excess']:+.1f}% vs SPY ({ld['why'].lower()})"))
        if niche.etf in ld["capex_niches"]:
            raw += 1.0
            parts.append((1.0, f"{ld['ticker']} spending news: its capex is this niche's revenue"))
    parts.sort(key=lambda p: -p[0])
    return squash(raw, 3.0), [p[1] for p in parts[:3]]


def tape(niche: Niche, daily: dict[str, list[Candle]], intraday: dict[str, list[Candle]], now_ms: int) -> dict | None:
    bars, spy = daily.get(niche.etf), daily.get(BENCHMARK)
    if not bars or not spy or len(bars) < 25 or len(spy) < 25:
        return None
    _, today = mk.today_move(bars, intraday.get(niche.etf))
    _, spy_today = mk.today_move(spy, intraday.get(BENCHMARK))
    if today is None or spy_today is None:
        return None
    excess = today - spy_today
    prev = (mk.ret(bars, 1, 1) or 0) - (mk.ret(spy, 1, 1) or 0)
    five = (mk.ret(bars, 5) or 0) - (mk.ret(spy, 5) or 0)
    rs = squash(0.5 * excess + 0.3 * prev + 0.2 * five, 1.5)

    avg_vol = sum(b.v for b in bars[-21:-1]) / 20
    rvol = bars[-1].v / (avg_vol * mk.session_fraction(now_ms)) if avg_vol else 1.0
    flow = round((1 if excess >= 0 else -1) * squash(max(0.0, rvol - 0.8), 0.7), 1)

    held = [daily[h] for h in niche.holdings if daily.get(h) and len(daily[h]) >= 21]
    if held:
        up = sum((mk.today_move(h, None)[1] or 0) > 0 for h in held) / len(held)
        above = sum(h[-1].c > mk.sma(h, 20) for h in held) / len(held)
        breadth = round(100 * (up + above - 1), 1)
    else:
        breadth = 0.0
    return {"today": round(today, 2), "excess": round(excess, 2), "rs": rs, "flow": flow, "breadth": breadth, "rvol": round(rvol, 2)}


def momentum_ranks(daily: dict[str, list[Candle]], days: int = 3) -> dict[str, list[int]]:
    """Each niche's rank by excess return over each of the last `days` completed sessions (1 = best)."""
    spy = daily.get(BENCHMARK)
    out: dict[str, list[int]] = {n.etf: [] for n in NICHES}
    if not spy:
        return out
    for back in range(1, days + 1):
        rows = []
        for n in NICHES:
            bars = daily.get(n.etf)
            r, s = (mk.ret(bars, 1, back) if bars else None), mk.ret(spy, 1, back)
            if r is not None and s is not None:
                rows.append((r - s, n.etf))
        for i, (_, etf) in enumerate(sorted(rows, reverse=True)):
            out[etf].append(i + 1)
    return out


def next_session(row: Row, ranks: list[int], total: int, leaders: list[dict]) -> str:
    """Stage 3d: a bias for the next session from momentum persistence and unfinished spillover. Scheduled
    catalysts apply to every niche, so the board lists them once."""
    notes = []
    if len(ranks) >= 3 and all(r <= 3 for r in ranks[:3]) and row.rank <= 3:
        notes.append("Bullish: top 3 for 4 sessions running")
    elif len(ranks) >= 3 and all(r > total - 3 for r in ranks[:3]) and row.rank > total - 3:
        notes.append("Bearish: bottom 3 for 4 sessions running")
    for ld in leaders:
        if row.etf in ld["niches"] and row.excess is not None and abs(ld["z"]) >= LEADER_MOVE_Z:
            follow = SPILLOVER * ld["excess"]
            if (follow > 0 and row.excess < follow / 2) or (follow < 0 and row.excess > follow / 2):
                notes.append(f"Catch-up {'up' if follow > 0 else 'down'} likely: has not followed {ld['ticker']} yet")
    return "; ".join(notes)


def rotation_alert(rows: list[Row], morning: dict[str, int] | None) -> str | None:
    """The META-then-UNH pattern: tech falls from the top of the board while defensives climb into the top 3."""
    by = {r.etf: r for r in rows}
    top3 = {r.etf for r in rows[:3]}
    defensive_top = [e for e in DEFENSIVE if e in top3]
    tech = by.get("XLK")
    if not tech or len(defensive_top) < 2:
        return None
    fell = morning and morning.get("XLK", 99) <= 3 and tech.rank >= len(rows) - 2
    red = tech.excess is not None and tech.excess <= -0.5
    if fell or red:
        names = ", ".join(by[e].name.lower() for e in defensive_top)
        return (f"Risk-to-defensive rotation: technology is {tech.excess:+.1f}% vs SPY while {names} lead. "
                "Money is leaving tech for defensives; favour defensive longs and be careful with tech longs.")
    return None


def build_board(daily: dict[str, list[Candle]], intraday: dict[str, list[Candle]], releases: list[Release],
                now_ms: int, headlines: dict[str, list[str]] | None = None, morning: dict[str, int] | None = None) -> dict:
    z, chips, facts = macro_drivers(daily, intraday, releases, now_ms)
    regime = detect_regime(facts)
    zr = read_for_regime(z, regime)
    leaders = leader_moves(daily, intraday, headlines or {})

    rows: list[Row] = []
    for n in NICHES:
        t = tape(n, daily, intraday, now_ms)
        if t is None:
            continue
        news, reasons = news_impulse(n, zr, leaders)
        score = round(WEIGHTS["news"] * news + WEIGHTS["rs"] * t["rs"] + WEIGHTS["flow"] * t["flow"]
                      + WEIGHTS["breadth"] * t["breadth"], 1)
        tape_score = (WEIGHTS["rs"] * t["rs"] + WEIGHTS["flow"] * t["flow"] + WEIGHTS["breadth"] * t["breadth"]) / 0.6
        rd, action = read(news, tape_score)
        if not reasons:
            reasons = ["No driver points at this niche today"]
        reasons.append(f"Tape: {t['excess']:+.1f}% vs SPY today, volume {t['rvol']:.1f}x normal")
        rows.append(Row(n.etf, n.name, score, label(score), news, t["rs"], t["flow"], t["breadth"], t["today"],
                        t["excess"], rd, action, reasons))
    rows.sort(key=lambda r: -r.score)
    for i, r in enumerate(rows):
        r.rank = i + 1

    ranks = momentum_ranks(daily)
    tomorrow = [r for r in upcoming_high(releases, now_ms, 30) if ny_time(r.time).date() != ny_time(now_ms).date()]
    for r in rows:
        r.next_session = next_session(r, ranks.get(r.etf, []), len(rows), leaders)

    return {
        "regime": regime,
        "regime_label": REGIMES[regime],
        "regime_note": REGIME_NOTES[regime],
        "drivers": [c.to_dict() for c in chips],
        "z": zr,
        "releases": [r.to_dict() for r in releases],
        "leaders": leaders,
        "rows": [r.to_dict() for r in rows],
        "bull": [r.etf for r in rows if r.score >= 20][:2],
        "bear": [r.etf for r in reversed(rows) if r.score <= -20][:2],
        "rotation": rotation_alert(rows, morning),
        "tomorrow": [r.to_dict() for r in tomorrow],
    }
