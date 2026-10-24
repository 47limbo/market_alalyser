"""The watchlist: each ticker, the Hyperliquid market that charts it, and how to search for its news.

Stocks and index ETFs trade on Hyperliquid as HIP-3 perpetuals (xyz: and mkts: dexes) around the clock.
The real share or ETF price from Yahoo Finance is the fallback chart when a Hyperliquid market fails.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Asset:
    ticker: str  # what the user calls it
    coin: str  # Hyperliquid market used for the chart
    kind: str  # "stock", "etf" or "crypto"
    name: str
    yahoo: str  # Yahoo Finance symbol for the fallback chart
    news_query: str  # Google News search for this asset's headlines

    def to_dict(self) -> dict:
        return asdict(self)


WATCHLIST: list[Asset] = [
    Asset("NVDA", "xyz:NVDA", "stock", "Nvidia", "NVDA", '"Nvidia" OR NVDA stock'),
    Asset("TSLA", "xyz:TSLA", "stock", "Tesla", "TSLA", '"Tesla" OR TSLA stock'),
    Asset("AAPL", "xyz:AAPL", "stock", "Apple", "AAPL", '"Apple" AAPL stock'),
    Asset("AMD", "xyz:AMD", "stock", "AMD", "AMD", '"Advanced Micro Devices" OR AMD stock'),
    Asset("MSFT", "xyz:MSFT", "stock", "Microsoft", "MSFT", '"Microsoft" MSFT stock'),
    Asset("AMZN", "xyz:AMZN", "stock", "Amazon", "AMZN", '"Amazon" AMZN stock'),
    Asset("META", "xyz:META", "stock", "Meta Platforms", "META", '"Meta Platforms" OR META stock'),
    Asset("PLTR", "xyz:PLTR", "stock", "Palantir", "PLTR", '"Palantir" OR PLTR stock'),
    Asset("GOOGL", "xyz:GOOGL", "stock", "Alphabet", "GOOGL", '"Alphabet" OR "Google" GOOGL stock'),
    Asset("SPY", "mkts:US500", "etf", "S&P 500 (SPY)", "SPY", '"S&P 500" OR SPY stocks'),
    Asset("QQQ", "mkts:USTECH", "etf", "Nasdaq 100 (QQQ)", "QQQ", '"Nasdaq 100" OR QQQ OR Nasdaq stocks'),
    Asset("IWM", "mkts:SMALL2000", "etf", "Russell 2000 (IWM)", "IWM", '"Russell 2000" OR IWM small caps'),
    Asset("BTC", "BTC", "crypto", "Bitcoin", "BTC-USD", "Bitcoin OR BTC price"),
    Asset("SOL", "SOL", "crypto", "Solana", "SOL-USD", "Solana OR SOL crypto price"),
]

_BY_KEY = {k.upper(): a for a in WATCHLIST for k in (a.ticker, a.coin)}


def find(symbol: str) -> Asset | None:
    """Look up by ticker ("NVDA") or by Hyperliquid market ("xyz:NVDA")."""
    return _BY_KEY.get(symbol.strip().upper())
