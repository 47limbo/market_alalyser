"""The niches the sector board ranks, and the liquid names inside each one.

Each niche is an ETF the board measures plus its biggest, most liquid holdings, which give breadth and the
Stage 4 shortlist. `profile` names the row of the sensitivity matrix (rules.py) the niche reacts like.
Edit these lists to add niches or names; nothing else needs to change.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Niche:
    etf: str
    name: str
    profile: str  # row of rules.SENSITIVITY
    holdings: tuple[str, ...]
    defensive: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


NICHES: list[Niche] = [
    Niche("XLK", "Technology", "XLK", ("AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD")),
    Niche("SMH", "Semiconductors", "SMH", ("NVDA", "TSM", "AVGO", "AMD", "QCOM", "MU", "AMAT", "LRCX")),
    Niche("IGV", "Software", "XLK", ("MSFT", "ORCL", "CRM", "ADBE", "NOW", "PLTR", "INTU", "PANW")),
    Niche("CIBR", "Cybersecurity", "XLK", ("CRWD", "PANW", "FTNT", "ZS", "NET")),
    Niche("XLC", "Communication", "XLC", ("META", "GOOGL", "NFLX", "DIS", "TMUS", "VZ")),
    Niche("XLY", "Consumer discretionary", "XLY", ("AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "BKNG", "SBUX")),
    Niche("XRT", "Retail", "XLY", ("TGT", "TJX", "ROST", "BBY", "DKS", "ANF")),
    Niche("XLF", "Financials", "XLF", ("JPM", "BAC", "WFC", "GS", "MS", "V", "MA")),
    Niche("KRE", "Regional banks", "KRE", ("TFC", "RF", "HBAN", "KEY", "CFG", "ZION")),
    Niche("XLE", "Energy", "XLE", ("XOM", "CVX", "COP", "EOG", "SLB", "OXY")),
    Niche("XOP", "Oil and gas producers", "XLE", ("OXY", "DVN", "FANG", "APA", "EOG", "COP")),
    Niche("XLB", "Materials", "XLB", ("LIN", "FCX", "NEM", "SHW", "DOW", "NUE")),
    Niche("GDX", "Gold miners", "GDX", ("NEM", "GOLD", "AEM", "WPM")),
    Niche("XLI", "Industrials", "XLI", ("GE", "CAT", "RTX", "UNP", "HON", "DE", "BA")),
    Niche("ITA", "Aerospace and defense", "XLI", ("LMT", "RTX", "NOC", "GD", "BA")),
    Niche("IYT", "Transports", "IYT", ("UNP", "UPS", "FDX", "CSX", "ODFL")),
    Niche("JETS", "Airlines", "JETS", ("DAL", "UAL", "AAL", "LUV")),
    Niche("XLV", "Healthcare", "XLV", ("LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO"), defensive=True),
    Niche("XBI", "Biotech", "XBI", ("VRTX", "REGN", "MRNA", "BIIB", "ALNY")),
    Niche("XLP", "Consumer staples", "XLP", ("PG", "COST", "KO", "PEP", "WMT", "PM"), defensive=True),
    Niche("XLU", "Utilities", "XLU", ("NEE", "SO", "DUK", "CEG", "VST", "AEP"), defensive=True),
    Niche("XLRE", "Real estate", "XLRE", ("PLD", "AMT", "EQIX", "O", "SPG")),
    Niche("ITB", "Homebuilders", "ITB", ("DHI", "LEN", "PHM", "TOL", "HD", "LOW")),
    Niche("IWM", "Small caps", "IWM", ()),
    Niche("QQQ", "Nasdaq 100", "XLK", ()),
]
BENCHMARK = "SPY"
_BY_ETF = {n.etf: n for n in NICHES}

# company names for news searches and labels; tickers missing here just use the ticker
NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AVGO": "Broadcom", "ORCL": "Oracle", "CRM": "Salesforce",
    "ADBE": "Adobe", "AMD": "AMD", "TSM": "TSMC", "QCOM": "Qualcomm", "MU": "Micron", "AMAT": "Applied Materials",
    "LRCX": "Lam Research", "NOW": "ServiceNow", "PLTR": "Palantir", "INTU": "Intuit", "PANW": "Palo Alto Networks",
    "CRWD": "CrowdStrike", "FTNT": "Fortinet", "ZS": "Zscaler", "NET": "Cloudflare", "META": "Meta Platforms",
    "GOOGL": "Alphabet", "NFLX": "Netflix", "DIS": "Disney", "TMUS": "T-Mobile", "VZ": "Verizon", "AMZN": "Amazon",
    "TSLA": "Tesla", "HD": "Home Depot", "MCD": "McDonald's", "NKE": "Nike", "LOW": "Lowe's", "BKNG": "Booking",
    "SBUX": "Starbucks", "TGT": "Target", "TJX": "TJX", "ROST": "Ross Stores", "BBY": "Best Buy",
    "DKS": "Dick's Sporting Goods", "ANF": "Abercrombie & Fitch", "JPM": "JPMorgan", "BAC": "Bank of America",
    "WFC": "Wells Fargo", "GS": "Goldman Sachs", "MS": "Morgan Stanley", "V": "Visa", "MA": "Mastercard",
    "TFC": "Truist", "RF": "Regions Financial", "HBAN": "Huntington Bancshares", "KEY": "KeyCorp",
    "CFG": "Citizens Financial", "ZION": "Zions", "XOM": "Exxon Mobil", "CVX": "Chevron", "COP": "ConocoPhillips",
    "EOG": "EOG Resources", "SLB": "SLB", "OXY": "Occidental", "DVN": "Devon Energy", "FANG": "Diamondback Energy",
    "APA": "APA", "LIN": "Linde", "FCX": "Freeport-McMoRan", "NEM": "Newmont", "SHW": "Sherwin-Williams",
    "DOW": "Dow", "NUE": "Nucor", "GOLD": "Barrick", "AEM": "Agnico Eagle", "WPM": "Wheaton Precious Metals",
    "GE": "GE Aerospace", "CAT": "Caterpillar", "RTX": "RTX", "UNP": "Union Pacific", "HON": "Honeywell",
    "DE": "Deere", "BA": "Boeing", "LMT": "Lockheed Martin", "NOC": "Northrop Grumman", "GD": "General Dynamics",
    "UPS": "UPS", "FDX": "FedEx", "CSX": "CSX", "ODFL": "Old Dominion", "DAL": "Delta Air Lines",
    "UAL": "United Airlines", "AAL": "American Airlines", "LUV": "Southwest Airlines", "LLY": "Eli Lilly",
    "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "ABBV": "AbbVie", "MRK": "Merck", "TMO": "Thermo Fisher",
    "VRTX": "Vertex", "REGN": "Regeneron", "MRNA": "Moderna", "BIIB": "Biogen", "ALNY": "Alnylam",
    "PG": "Procter & Gamble", "COST": "Costco", "KO": "Coca-Cola", "PEP": "PepsiCo", "WMT": "Walmart",
    "PM": "Philip Morris", "NEE": "NextEra Energy", "SO": "Southern Company", "DUK": "Duke Energy",
    "CEG": "Constellation Energy", "VST": "Vistra", "AEP": "American Electric Power", "PLD": "Prologis",
    "AMT": "American Tower", "EQIX": "Equinix", "O": "Realty Income", "SPG": "Simon Property", "DHI": "D.R. Horton",
    "LEN": "Lennar", "PHM": "PulteGroup", "TOL": "Toll Brothers", "ASML": "ASML", "HCA": "HCA Healthcare",
    "HUM": "Humana", "ELV": "Elevance Health", "CVS": "CVS Health", "CI": "Cigna", "NVO": "Novo Nordisk",
}


def niche(etf: str) -> Niche | None:
    return _BY_ETF.get(etf.upper())


def niches_of(ticker: str) -> list[Niche]:
    """Every niche that holds the ticker, or whose ETF it is."""
    t = ticker.upper()
    return [n for n in NICHES if t == n.etf or t in n.holdings]


def universe() -> list[str]:
    """Every ticker the board reads: the benchmark, each niche ETF and its holdings."""
    seen = {BENCHMARK: None}
    for n in NICHES:
        seen.setdefault(n.etf, None)
        for h in n.holdings:
            seen.setdefault(h, None)
    return list(seen)


def name_of(ticker: str) -> str:
    return NAMES.get(ticker.upper(), ticker.upper())
