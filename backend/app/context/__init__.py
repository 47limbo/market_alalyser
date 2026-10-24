"""The news and macro context for one asset: rates, the Fed, earnings, headlines and optional deep research.

All sources are fetched in parallel and cached for a few minutes. A source that cannot be reached is listed
as missing and simply left out of the score.
"""

import asyncio
import random
import time
from datetime import datetime, timezone

from ..watchlist import Asset
from .confidence import bias_label, context_bias, score_setup
from .earnings import fetch_earnings
from .factor import Factor
from .macro import fomc_factor, macro_factors
from .news import news_factors
from .sec import sec_factors
from .research import ResearchUnavailable, available as research_available, brief_factor, deep_research

CACHE_SECONDS = 600
RESEARCH_SECONDS = 3600
_cache: dict[str, tuple[float, dict]] = {}
_research: dict[str, dict] = {}
_research_running: dict[str, asyncio.Task] = {}

__all__ = ["get_context", "run_research", "research_status", "score_setup", "ResearchUnavailable"]


async def _gather(asset: Asset) -> tuple[list[Factor], list[str]]:
    today = datetime.now(timezone.utc).date()
    jobs = [macro_factors(asset.kind, today), news_factors(asset.name, asset.news_query, asset.kind, asset.yahoo)]
    if asset.kind == "stock":
        jobs += [fetch_earnings(asset.ticker, today), sec_factors(asset.ticker)]
    factors, missing = [], []
    for got in await asyncio.gather(*jobs, return_exceptions=True):
        if isinstance(got, Exception):
            missing.append(f"a source failed ({type(got).__name__})")
            continue
        factors += got[0]
        missing += got[1]
    return factors, missing


def demo_factors(asset: Asset) -> list[Factor]:
    """Made-up context for offline demo mode, so the panel can be seen without internet."""
    rnd = random.Random(sum(map(ord, asset.ticker)))
    today = datetime.now(timezone.utc).date()
    demo = [{"title": "Demo data: no real source", "url": "https://fred.stlouisfed.org/"}]
    out = [
        Factor("us10y", "Rates and yields", "10-year yield", "4.18% (-12 bp over 20 trading days). Falling long yields support valuations, a tailwind.", 0.48, 1.5, sources=demo),
        Factor("us2y", "Rates and yields", "2-year yield", "3.52% (-9 bp over 20 trading days). The 2-year tracks where traders expect the Fed rate; it is falling, so the market is pricing more cuts.", 0.3, 1.0, sources=demo),
        Factor("vix", "Rates and yields", "VIX", "17.2: normal.", 0.1, 1.0, sources=demo),
        fomc_factor(today, []),
        Factor("news", "News", f"{asset.name} headlines", "18 headlines in the last 2 days: 7 positive, 4 negative in tone.",
               round(rnd.uniform(-0.5, 0.6), 2), 1.0, sources=[dict(demo[0], title=f"Demo headline about {asset.name}", tone=0.5, source="Demo")]),
        Factor("macro_news", "Macro and politics", "Fed, inflation, trade and policy headlines", "40 headlines in the last 2 days: 11 positive, 13 negative in tone.",
               -0.12, 0.8, sources=demo),
    ]
    if asset.kind == "stock":
        out.append(Factor("earnings_next", "Earnings", "Next earnings", "2026-10-29 after the close (5 days). Shares can gap well past any stop on the report, so treat a new entry as higher risk until it is out.",
                          risk=0.35, sources=demo))
        out.append(Factor("eps_surprise", "Earnings", "Last EPS result", "Q2: EPS 1.05 vs 0.98 expected (+7.1%). Beat 4 of the last 4 quarters.", 0.65, 1.0, sources=demo))
    return out


async def get_context(asset: Asset, demo: bool = False) -> dict:
    key = asset.ticker
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        ctx = hit[1]
    else:
        factors, missing = (demo_factors(asset), []) if demo else await _gather(asset)
        ctx = {"factors": factors, "missing": missing, "fetched": int(time.time() * 1000)}
        _cache[key] = (time.time(), ctx)

    factors = list(ctx["factors"])
    brief = _research.get(key)
    if brief and time.time() * 1000 - brief["created"] < RESEARCH_SECONDS * 1000:
        factors.append(brief_factor(brief))
    else:
        brief = None
    bias = context_bias(factors)
    return {
        "asset": asset.to_dict(),
        "bias": round(bias, 3),
        "bias_label": bias_label(bias),
        "factors": factors,
        "missing": ctx["missing"],
        "fetched": ctx["fetched"],
        "research": brief,
        "research_available": research_available(),
        "research_running": key in _research_running and not _research_running[key].done(),
        "demo": demo,
    }


async def run_research(asset: Asset) -> dict:
    """Start (or join) a deep research run for the asset and wait for it."""
    key = asset.ticker
    task = _research_running.get(key)
    if task is None or task.done():
        task = asyncio.create_task(deep_research(asset.ticker, asset.name, asset.kind))
        _research_running[key] = task
    brief = await task
    _research[key] = brief
    return brief


def research_status(asset: Asset) -> dict | None:
    return _research.get(asset.ticker)
