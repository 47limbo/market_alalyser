"""Stage 4: the tickers to trade inside today's strongest and weakest niches.

Required: moves with the theme, liquid, room left to move, no news of its own against the trade.
Bonus: lagging a leader that already moved (the catch-up trade), and leading its niche today.
"""

from dataclasses import asdict, dataclass, field

from ..models import Candle
from . import market as mk
from .universe import niche, name_of

MIN_BETA, MIN_CORR = 1.0, 0.6
MIN_DOLLAR_VOLUME = 200e6
MIN_PRICE = 10.0
MIN_ATR_PCT = 2.0
MAX_MOVE_ATR = 2.0
PER_NICHE = 3


@dataclass
class Check:
    key: str
    label: str
    status: str  # pass, fail, n/a
    detail: str
    required: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Candidate:
    ticker: str
    name: str
    niche: str
    direction: str  # long or short
    price: float
    today: float
    checks: list[Check] = field(default_factory=list)
    qualifies: bool = False
    fit: float = 0.0  # 0 to 1, share of checks passed
    beta: float | None = None
    corr: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checks"] = [c.to_dict() for c in self.checks]
        return d


def evaluate(ticker: str, etf: str, direction: str, daily: dict[str, list[Candle]], leaders: list[dict],
             conflict: dict | None = None) -> Candidate | None:
    bars, nbars = daily.get(ticker), daily.get(etf)
    if not bars or not nbars or len(bars) < 30:
        return None
    long = direction == "long"
    _, today = mk.today_move(bars, None)
    _, niche_today = mk.today_move(nbars, None)
    today, niche_today = today or 0.0, niche_today or 0.0
    price = bars[-1].c
    c = Candidate(ticker, name_of(ticker), etf, direction, price, round(today, 2))
    add = c.checks.append

    beta, corr = mk.beta_corr(mk.daily_returns(nbars)[-60:], mk.daily_returns(bars)[-60:])
    c.beta, c.corr = (round(beta, 2) if beta is not None else None), (round(corr, 2) if corr is not None else None)
    ok = beta is not None and beta >= MIN_BETA and corr >= MIN_CORR
    add(Check("theme", "Moves with the theme", "pass" if ok else "fail",
              f"beta {beta:.2f}, correlation {corr:.2f} to {etf} (60 days)" if beta is not None else "not enough history", True))

    dollar = sum(b.c * b.v for b in bars[-21:-1]) / 20
    ok = dollar >= MIN_DOLLAR_VOLUME and price >= MIN_PRICE
    add(Check("liquidity", "Liquid enough to day trade", "pass" if ok else "fail",
              f"${dollar / 1e6:,.0f}M a day, price ${price:,.2f}", True))

    atr = mk.atr_pct(bars) or 0.0
    moved = abs(today) / atr if atr else 0.0
    ok = atr >= MIN_ATR_PCT and moved <= MAX_MOVE_ATR
    add(Check("room", "Room to move", "pass" if ok else "fail",
              f"ATR {atr:.1f}% of price, moved {moved:.1f} ATR today" + ("" if atr >= MIN_ATR_PCT else f" (needs {MIN_ATR_PCT:g}%)"), True))

    if conflict is None:
        add(Check("conflict", "No news of its own against the trade", "n/a", "not checked yet", True))
    else:
        add(Check("conflict", "No news of its own against the trade", "fail" if conflict["bad"] else "pass", conflict["detail"], True))

    lag = None
    for ld in leaders:
        if ticker in ld["peers"]:
            expected = (beta or 1.0) * ld["excess"] * 0.5
            gap = expected - today if long else today - expected
            if (expected > 0) == long and gap > 0:
                lag = f"{ld['ticker']} {ld['excess']:+.1f}% vs SPY; {ticker} has {abs(gap):.1f}% to catch up"
    add(Check("laggard", "Lagging a leader that moved", "pass" if lag else "n/a", lag or "no leader move to follow", False))

    lead = today - niche_today if long else niche_today - today
    add(Check("rs", f"{'Leading' if long else 'Weaker than'} its niche today", "pass" if lead > 0 else "fail",
              f"{today:+.1f}% vs {etf} {niche_today:+.1f}%", False))

    scored = [k for k in c.checks if k.status != "n/a"]
    c.fit = round(sum(k.status == "pass" for k in scored) / len(scored), 2) if scored else 0.0
    c.qualifies = all(k.status == "pass" for k in c.checks if k.required and k.status != "n/a")
    return c


def shortlist(board: dict, daily: dict[str, list[Candle]], conflicts: dict[str, dict] | None = None) -> list[dict]:
    """Up to three candidates for each of the top two bull and bottom two bear niches; SPY and QQQ when none stand out."""
    conflicts = conflicts or {}
    groups = []
    picks = [(etf, "long") for etf in board["bull"]] + [(etf, "short") for etf in board["bear"]]
    for etf, direction in picks:
        n = niche(etf)
        names = n.holdings if n and n.holdings else (etf,)
        cands = [evaluate(t, etf, direction, daily, board["leaders"], conflicts.get(t)) for t in names]
        cands = [c for c in cands if c]
        cands.sort(key=lambda c: (not c.qualifies, -c.fit, -(c.corr or 0)))
        row = next((r for r in board["rows"] if r["etf"] == etf), None)
        groups.append({"etf": etf, "name": n.name if n else etf, "direction": direction, "score": row["score"] if row else 0,
                       "label": row["label"] if row else "", "candidates": [c.to_dict() for c in cands[:PER_NICHE]]})
    if not groups:
        lean = sum(r["score"] for r in board["rows"]) / max(1, len(board["rows"]))
        direction = "long" if lean >= 0 else "short"
        for etf in ("SPY", "QQQ"):
            c = evaluate(etf, "SPY", direction, daily, [], conflicts.get(etf))
            if c:
                groups.append({"etf": etf, "name": "Index (no niche stands out)", "direction": direction, "score": round(lean, 1),
                               "label": "Index", "candidates": [c.to_dict()]})
    return groups


def conflict_from(direction: str, next_earnings: str | None, days_to_earnings: int | None, tones: list[float]) -> dict:
    """Own-news check: earnings within 2 sessions, or the stock's own headlines lean against the trade."""
    reasons = []
    bad = False
    if days_to_earnings is not None and days_to_earnings <= 2:
        bad = True
        reasons.append(f"earnings {next_earnings}")
    toned = [t for t in tones if t]
    avg = sum(toned) / len(toned) if toned else 0.0
    against = avg < -0.3 if direction == "long" else avg > 0.3
    if against and len(toned) >= 3:
        bad = True
        reasons.append(f"own headlines lean {'bearish' if avg < 0 else 'bullish'}")
    if not reasons:
        reasons.append("no earnings within 2 sessions" + (f" (next {next_earnings})" if next_earnings else "")
                       + f", {len(toned)} toned headlines")
    return {"bad": bad, "detail": "; ".join(reasons)}

