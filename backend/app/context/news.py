"""Headlines from Google News and Yahoo Finance RSS, scored with a small finance word list.

Headline scoring is crude on purpose: it reads tone, not meaning. It is one input among many, weighted
low, and the headlines are listed so you can read them yourself. Deep research reads the stories properly.
"""

import asyncio
import re

from .factor import Factor, clamp
from urllib.parse import parse_qs, urlparse

from .feeds import client, get_text, meta_description, now_ms, parse_rss

GOOGLE_NEWS = "https://news.google.com/rss/search"
NEWS_SHOWN = 10
YAHOO_NEWS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
BING_NEWS = "https://www.bing.com/news/search"
# quote pages, option contracts and insider-filing stubs are not news
JUNK = re.compile(r"\b[A-Z]{1,5}\d{6}[CP]\d{6,8}\b|options chain|stock price, news, quote|^form 4\b|\bquote & history\b", re.I)
DAY_MS = 86_400_000

# phrase -> tone, checked longest first so "rate cut" wins over "cut"
LEXICON = {
    # bullish
    "beats": 1, "beat estimates": 1.5, "tops estimates": 1.5, "record high": 1, "all-time high": 1, "surge": 1,
    "soar": 1, "rally": 1, "jumps": 0.8, "climbs": 0.6, "gains": 0.5, "rises": 0.5, "upgrade": 1, "upgraded": 1,
    "raises guidance": 1.5, "raises outlook": 1.5, "strong demand": 1, "buyback": 0.8, "outperform": 0.8,
    "rate cut": 1, "rate cuts": 1, "cuts rates": 1, "dovish": 1, "cooling inflation": 1, "inflation eases": 1,
    "soft landing": 0.8, "trade deal": 1, "tariff relief": 1, "approval": 0.6, "approved": 0.6, "inflows": 0.8,
    "partnership": 0.5, "bullish": 1, "rebound": 0.6,
    # bearish
    "misses": -1, "missed estimates": -1.5, "falls short": -1, "plunge": -1.2, "plunges": -1.2, "tumble": -1,
    "slump": -1, "sinks": -1, "drops": -0.6, "falls": -0.5, "slides": -0.6, "downgrade": -1, "downgraded": -1,
    "cuts guidance": -1.5, "lowers guidance": -1.5, "weak demand": -1, "layoffs": -0.6, "probe": -0.8,
    "investigation": -0.8, "lawsuit": -0.6, "antitrust": -0.8, "recall": -0.8, "ban": -0.8, "export controls": -1,
    "rate hike": -1, "rate hikes": -1, "hawkish": -1, "hot inflation": -1.2, "inflation rises": -1, "sticky inflation": -0.8,
    "tariff": -0.6, "tariffs": -0.6, "trade war": -1.2, "sanctions": -0.6, "shutdown": -0.8, "default": -1,
    "recession": -1, "selloff": -1, "sell-off": -1, "outflows": -0.8, "hack": -1, "bearish": -1, "crash": -1.5,
    "yields jump": -1, "yields surge": -1, "yields fall": 0.8, "yields drop": 0.8,
}
_PHRASES = sorted(LEXICON, key=len, reverse=True)

# headlines about the economy and politics that move the whole market
MACRO_QUERIES = {
    "stock": ['"Federal Reserve" OR Powell rates', "inflation CPI OR jobs report", "tariffs OR trade war OR White House economy OR Congress budget"],
    "etf": ['"Federal Reserve" OR Powell rates', "inflation CPI OR jobs report", "tariffs OR trade war OR White House economy OR Congress budget"],
    "crypto": ['"Federal Reserve" OR Powell rates', "crypto regulation OR SEC crypto OR stablecoin bill", "Bitcoin ETF flows"],
}


def tone(title: str) -> float:
    text = " " + re.sub(r"[^a-z0-9%\- ]", " ", title.lower()) + " "
    total = 0.0
    for phrase in _PHRASES:
        pattern = f" {phrase} "
        if pattern in text:
            total += LEXICON[phrase]
            text = text.replace(pattern, " ")
    return clamp(total / 2)


def mentions(title: str, keywords: tuple[str, ...]) -> bool:
    text = title.lower()
    return any(re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", text) for k in keywords)


def headline_factor(key: str, group: str, label: str, items: list[dict], weight: float, show: int = 5) -> Factor:
    scored = [dict(i, tone=tone(i["title"])) for i in items]
    toned = [i for i in scored if i["tone"]]
    avg = sum(i["tone"] for i in toned) / len(toned) if toned else 0.0
    ups, downs = sum(i["tone"] > 0 for i in scored), sum(i["tone"] < 0 for i in scored)
    detail = f"{len(scored)} headlines in the last 2 days: {ups} positive, {downs} negative in tone."
    if not scored:
        detail = "No headlines in the last 2 days."
    picks = sorted(scored, key=lambda i: -(i["published"] or 0))[:show]  # newest first
    sources = [{"title": i["title"], "url": i["url"], "source": i["source"], "tone": i["tone"], "published": i["published"],
                "summary": i.get("summary", "")} for i in picks]
    # few toned headlines are weak evidence, so shrink the score toward zero
    confidence = min(1.0, len(toned) / 6)
    return Factor(key, group, label, detail, score=avg * confidence, weight=weight, sources=sources)


async def search(http, query: str) -> list[dict]:
    text = await get_text(http, GOOGLE_NEWS, q=f"{query} when:2d", hl="en-US", gl="US", ceid="US:en")
    cutoff = now_ms() - 2 * DAY_MS
    return [i for i in parse_rss(text, limit=40) if not i["published"] or i["published"] >= cutoff]


async def yahoo_headlines(http, symbol: str) -> list[dict]:
    text = await get_text(http, YAHOO_NEWS, s=symbol, region="US", lang="en-US")
    cutoff = now_ms() - 2 * DAY_MS
    items = [dict(i, source=i["source"] or "Yahoo Finance") for i in parse_rss(text, limit=30)]
    return [i for i in items if not i["published"] or i["published"] >= cutoff]


async def bing_headlines(http, query: str) -> list[dict]:
    text = await get_text(http, BING_NEWS, q=query, format="rss", qft='interval="7"')
    cutoff = now_ms() - 2 * DAY_MS
    items = []
    for i in parse_rss(text, limit=30):
        # Bing wraps links in a click tracker; the real article address is its url= parameter
        real = parse_qs(urlparse(i["url"]).query).get("url")
        items.append(dict(i, url=real[0] if real else i["url"], source=i["source"] or urlparse(real[0] if real else i["url"]).netloc.removeprefix("www.")))
    return [i for i in items if not i["published"] or i["published"] >= cutoff]


def normal(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())[:60]


def merge(*lists: list[dict]) -> list[dict]:
    """One copy of each story, keeping the copy that has a summary."""
    best: dict[str, dict] = {}
    for items in lists:
        for i in items:
            key = normal(i["title"])
            if key not in best or (i.get("summary") and not best[key].get("summary")):
                best[key] = i
    return list(best.values())


async def add_summaries(http, items: list[dict]) -> None:
    """Fill missing summaries from each article's own preview text (Google News links cannot be opened this way)."""
    async def one(i):
        if i.get("summary") or not i["url"] or "news.google.com" in i["url"]:
            return
        try:
            resp = await http.get(i["url"], timeout=6)
            if resp.status_code == 200 and "html" in resp.headers.get("content-type", ""):
                i["summary"] = meta_description(resp.text)
        except Exception:
            pass

    await asyncio.gather(*(one(i) for i in items))


async def news_factors(name: str, query: str, kind: str, yahoo: str | None = None, keywords: tuple[str, ...] = ()) -> tuple[list[Factor], list[str]]:
    missing = []
    queries = [query] + MACRO_QUERIES.get(kind, MACRO_QUERIES["stock"])
    async with client() as http:
        jobs = [search(http, q) for q in queries] + [bing_headlines(http, name)]
        if yahoo:
            jobs.append(yahoo_headlines(http, yahoo))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        yahoo_items = results.pop() if yahoo else []
        bing_items = results.pop()
        for got, label in ((yahoo_items, "Yahoo Finance headlines"), (bing_items, "Bing News headlines")):
            if isinstance(got, Exception):
                missing.append(label)
        yahoo_items = [] if isinstance(yahoo_items, Exception) else yahoo_items
        bing_items = [] if isinstance(bing_items, Exception) else bing_items
        google_items = [] if isinstance(results[0], Exception) else results[0]
        if isinstance(results[0], Exception):
            missing.append("Google News (asset headlines)")
        asset_items = [i for i in merge(yahoo_items, bing_items, google_items) if not JUNK.search(i["title"])]
        if keywords:
            # keep only stories that actually name the asset; searches and feeds also return loosely related ones
            asset_items = [i for i in asset_items if mentions(i["title"], keywords)]
        newest = sorted(asset_items, key=lambda i: -(i["published"] or 0))[:NEWS_SHOWN]
        await add_summaries(http, newest)
    macro_items, seen = [], set()
    for r in results[1:]:
        if isinstance(r, Exception):
            continue
        for i in r:
            if i["title"] not in seen:
                seen.add(i["title"])
                macro_items.append(i)
    if all(isinstance(r, Exception) for r in results[1:]):
        missing.append("Google News (macro and political headlines)")
    factors = []
    if asset_items or not isinstance(results[0], Exception):
        factors.append(headline_factor("news", "News", f"Latest on {name}", asset_items, weight=1.0, show=NEWS_SHOWN))
    if macro_items:
        label = "Crypto-wide: Fed, regulation and ETF flows" if kind == "crypto" else "Market-wide: Fed, inflation, trade and politics"
        factors.append(headline_factor("macro_news", "Macro and politics", label, macro_items, weight=0.8))
    return factors, missing
