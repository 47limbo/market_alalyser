"""The strategy's rule tables, copied from the strategy doc so they can be edited in one place.

SENSITIVITY  Stage 2a: sign of a sector's usual same-day move when a driver rises (2 strong, 1, 0, -1, -2 strong)
LEADERS      Stage 2b: leader-to-peer spillover, including second-order routes like hyperscaler capex
REGIMES      Stage 3a: the market regime, which decides how jobs and inflation surprises are read
"""

from dataclasses import dataclass

# the drivers the matrix has a column for; Stage 1 turns each into a signed z-score
# (how to say it when the driver rises, and when it falls)
DRIVER_WORDS = {
    "y10": ("10-year yield up", "10-year yield down"),
    "oil": ("Oil up", "Oil down"),
    "usd": ("Dollar up", "Dollar down"),
    "cpi": ("Inflation data hot", "Inflation data cool"),
    "jobs": ("Jobs and growth data strong", "Jobs and growth data weak"),
    "vix": ("VIX up", "VIX down"),
    "copper": ("Copper up", "Copper down"),
}
DRIVERS = {
    "y10": "10-year yield",
    "oil": "Crude oil",
    "usd": "US dollar",
    "cpi": "Hot inflation data",
    "jobs": "Strong jobs and growth data",
    "vix": "VIX",
    "copper": "Copper",
}

SENSITIVITY: dict[str, dict[str, int]] = {
    #         y10  oil  usd  cpi  jobs  vix  copper
    "XLK":  dict(y10=-1, oil=-1, usd=-1, cpi=-2, jobs=0, vix=-2, copper=1),
    "SMH":  dict(y10=-1, oil=-1, usd=-1, cpi=-2, jobs=1, vix=-2, copper=1),
    "XLC":  dict(y10=-1, oil=-1, usd=-1, cpi=-1, jobs=0, vix=-1, copper=0),
    "XLY":  dict(y10=-1, oil=-2, usd=-1, cpi=-1, jobs=1, vix=-2, copper=1),
    "XLF":  dict(y10=1, oil=0, usd=0, cpi=0, jobs=1, vix=-1, copper=1),
    "KRE":  dict(y10=1, oil=0, usd=0, cpi=-1, jobs=1, vix=-2, copper=1),
    "XLE":  dict(y10=1, oil=2, usd=-1, cpi=1, jobs=1, vix=-1, copper=1),
    "XLB":  dict(y10=0, oil=1, usd=-2, cpi=1, jobs=1, vix=-1, copper=2),
    "XLI":  dict(y10=0, oil=-1, usd=-1, cpi=-1, jobs=1, vix=-1, copper=1),
    "IYT":  dict(y10=0, oil=-2, usd=-1, cpi=-1, jobs=1, vix=-1, copper=1),
    "XLV":  dict(y10=0, oil=0, usd=0, cpi=0, jobs=0, vix=1, copper=0),
    "XBI":  dict(y10=-2, oil=0, usd=0, cpi=-1, jobs=0, vix=-2, copper=0),
    "XLP":  dict(y10=-1, oil=-1, usd=-1, cpi=0, jobs=0, vix=1, copper=0),
    "XLU":  dict(y10=-2, oil=0, usd=0, cpi=-1, jobs=-1, vix=1, copper=0),
    "XLRE": dict(y10=-2, oil=0, usd=0, cpi=-2, jobs=-1, vix=-1, copper=0),
    "ITB":  dict(y10=-2, oil=-1, usd=0, cpi=-2, jobs=0, vix=-1, copper=0),
    "IWM":  dict(y10=-2, oil=-1, usd=-1, cpi=-2, jobs=1, vix=-2, copper=1),
    "JETS": dict(y10=0, oil=-2, usd=0, cpi=-1, jobs=1, vix=-2, copper=0),
    "GDX":  dict(y10=-1, oil=1, usd=-2, cpi=1, jobs=-1, vix=1, copper=1),
}


@dataclass(frozen=True)
class Leader:
    ticker: str
    niches: tuple[str, ...]  # niches that move the same way when it moves
    peers: tuple[str, ...]  # tickers that usually follow (for the laggard check)
    why: str
    capex: tuple[str, ...] = ()  # niches that gain when it raises spending, whatever its own shares do


HYPERSCALER_CAPEX = ("SMH", "XLU")
LEADERS: list[Leader] = [
    Leader("NVDA", ("SMH", "XLK"), ("AMD", "AVGO", "TSM", "MU", "QCOM"), "AI compute demand read-through"),
    Leader("TSM", ("SMH",), ("NVDA", "AMD", "AMAT", "LRCX", "AVGO"), "Foundry volume is chip demand"),
    Leader("MSFT", ("IGV", "XLK"), ("ORCL", "CRM", "NOW", "ADBE"), "Cloud and AI spending", HYPERSCALER_CAPEX),
    Leader("GOOGL", ("XLC",), ("META",), "Ad market and cloud", HYPERSCALER_CAPEX),
    Leader("AMZN", ("XLY",), ("TGT", "WMT", "COST"), "Consumer and cloud", HYPERSCALER_CAPEX),
    Leader("META", ("XLC",), ("GOOGL",), "Ad market", HYPERSCALER_CAPEX),
    Leader("ASML", ("SMH",), ("AMAT", "LRCX"), "Chip-equipment cycle"),
    Leader("JPM", ("XLF", "KRE"), ("BAC", "WFC", "GS", "MS"), "Credit quality and net interest margin"),
    Leader("BAC", ("XLF", "KRE"), ("JPM", "WFC", "TFC", "RF"), "Credit quality and net interest margin"),
    Leader("UNH", ("XLV",), ("HUM", "ELV", "CVS", "CI"), "Medical cost trend"),
    Leader("LLY", ("XLV", "XBI"), ("NVO",), "Obesity drug demand"),
    Leader("XOM", ("XLE", "XOP"), ("CVX", "COP", "EOG", "OXY", "SLB"), "Same commodity"),
    Leader("CVX", ("XLE", "XOP"), ("XOM", "COP", "EOG", "OXY"), "Same commodity"),
    Leader("WMT", ("XLP", "XRT"), ("COST", "TGT"), "Consumer health"),
    Leader("COST", ("XLP", "XRT"), ("WMT", "TGT"), "Consumer health"),
    Leader("AAPL", ("XLK", "SMH"), ("QCOM", "AVGO", "TSM"), "iPhone volumes"),
    Leader("TSLA", ("XLY",), (), "EV demand"),
    Leader("FDX", ("IYT", "XLI"), ("UPS",), "Freight volumes"),
    Leader("UPS", ("IYT", "XLI"), ("FDX",), "Freight volumes"),
    Leader("DHI", ("ITB",), ("LEN", "PHM", "TOL", "HD", "LOW"), "Housing demand"),
    Leader("LEN", ("ITB",), ("DHI", "PHM", "TOL"), "Housing demand"),
    Leader("CRWD", ("CIBR",), ("PANW", "ZS", "FTNT"), "Security budgets"),
    Leader("PANW", ("CIBR",), ("CRWD", "ZS", "FTNT"), "Security budgets"),
    Leader("NFLX", ("XLC",), ("DIS",), "Subscriber trends"),
    Leader("CAT", ("XLI", "XLB"), ("DE",), "Global capex cycle"),
]
LEADER_BY_TICKER = {ld.ticker: ld for ld in LEADERS}
SPILLOVER = 0.5  # share of a leader's surprise passed to its niches
CAPEX_WORDS = ("capex", "capital expenditure", "capital spending", "spending plan", "data center spending", "ai spending")

REGIMES = {
    "risk_off": "Risk-off shock",
    "inflation": "Inflation scare",
    "growth_scare": "Growth scare",
    "goldilocks": "Goldilocks easing",
    "risk_on": "Risk-on growth",
    "mixed": "Mixed",
}
REGIME_NOTES = {
    "risk_off": "Gold and defensives lead, high beta and momentum lag. Trade smaller.",
    "inflation": "Energy, materials and banks lead; long-duration tech, REITs and builders lag. Strong jobs read as inflationary.",
    "growth_scare": "Staples, healthcare and utilities lead; cyclicals, small caps and transports lag.",
    "goldilocks": "Small caps, builders, tech and REITs lead; energy and defensives lag.",
    "risk_on": "Semis, discretionary, small caps and banks lead; staples and utilities lag.",
    "mixed": "No clear regime: let the board's tape decide.",
}


def detect_regime(m: dict) -> str:
    """m holds: vix, vix_1d (%), y10_5d (bp), oil_5d (%), copper_5d (%), spy_above_20d (bool),
    hot_inflation (z of the latest inflation release, or 0)."""
    vix = m.get("vix") or 0
    if vix > 25 or (m.get("vix_1d") or 0) >= 20:
        return "risk_off"
    y5, inf = m.get("y10_5d") or 0, m.get("hot_inflation") or 0
    if y5 > 15 and ((m.get("oil_5d") or 0) > 3 or inf > 0.5):
        return "inflation"
    if y5 < -15 and ((m.get("copper_5d") or 0) < -2 or not m.get("spy_above_20d")):
        return "growth_scare"
    if inf < -0.5 and m.get("spy_above_20d") and y5 <= 0:
        return "goldilocks"
    if m.get("spy_above_20d") and vix < 18:
        return "risk_on"
    return "mixed"


def label(score: float) -> str:
    return ("Strong bull" if score >= 50 else "Bull" if score >= 20 else "Strong bear" if score <= -50
            else "Bear" if score <= -20 else "Neutral")


def read(news: float, tape: float) -> tuple[str, str]:
    """Stage 3c: news impulse against what prices are doing. Returns (read, action)."""
    n = 1 if news > 15 else -1 if news < -15 else 0
    t = 1 if tape > 10 else -1 if tape < -10 else 0
    if n == 1 and t == 1:
        return "Confirmed bull", "Trade with the trend"
    if n == -1 and t == -1:
        return "Confirmed bear", "Short or avoid"
    if n == 1 and t == -1:
        return "Sell the news", "No long: check where the money went"
    if n == -1 and t == 1:
        return "Bad news priced in", "No short: reversal long only with full alignment"
    if n == 0 and t != 0:
        return "Tape only", "Smaller size: no headline behind it"
    return "Quiet", "Nothing to do"
