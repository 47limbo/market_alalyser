"""Reported results straight from the company's SEC filings (EDGAR, free, no key).

Reads quarterly diluted EPS and revenue from the XBRL data in 10-Q and 10-K filings, and lists the latest
filings, including the 8-K that carries each earnings press release.
"""

import asyncio
import os
import re

import httpx

from .factor import Factor, clamp

# SEC company numbers (CIK) for the watchlist stocks
CIK = {"NVDA": 1045810, "TSLA": 1318605, "AAPL": 320193, "AMD": 2488, "MSFT": 789019,
       "AMZN": 1018724, "META": 1326801, "PLTR": 1321655, "GOOGL": 1652044}
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# the SEC asks automated tools to say who they are; set MA_SEC_CONTACT to your email if you like
USER_AGENT = f"MarketAnalyser/1.0 {os.environ.get('MA_SEC_CONTACT', 'market-analyser@users.noreply.github.com')}"
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
REVENUE_TAGS = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
QUARTER = re.compile(r"^CY(\d{4})Q([1-4])$")


def quarterly(facts: dict, tags: list[str], unit: str) -> dict[tuple[int, int], float]:
    """{(year, quarter): value} for single-quarter facts, from the first tag the company reports."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        out = {}
        for item in gaap.get(tag, {}).get("units", {}).get(unit, []):
            m = QUARTER.match(item.get("frame", ""))
            if m:
                out[(int(m[1]), int(m[2]))] = float(item["val"])
        if out:
            return out
    return {}


def growth(series: dict[tuple[int, int], float]) -> tuple[tuple[int, int], float, float | None] | None:
    """Latest quarter, its value, and the change against the same quarter a year earlier (%)."""
    if not series:
        return None
    (y, q) = max(series)
    now, before = series[(y, q)], series.get((y - 1, q))
    pct = (now - before) / abs(before) * 100 if before else None
    return (y, q), now, pct


def sec_factor(ticker: str, facts: dict, filings: list[dict]) -> Factor | None:
    eps = growth(quarterly(facts, EPS_TAGS, "USD/shares"))
    rev = growth(quarterly(facts, REVENUE_TAGS, "USD"))
    if not eps and not rev:
        return None
    parts, score = [], 0.0
    if eps:
        (y, q), v, pct = eps
        parts.append(f"Diluted EPS {v:.2f} in calendar Q{q} {y}" + (f" ({pct:+.0f}% on a year earlier)" if pct is not None else ""))
        if pct is not None:
            score += clamp(pct / 40) * 0.6
    if rev:
        (y, q), v, pct = rev
        parts.append(f"revenue ${v / 1e9:.1f}bn" + (f" ({pct:+.0f}%)" if pct is not None else ""))
        if pct is not None:
            score += clamp(pct / 25) * 0.4
    detail = "; ".join(parts) + ". Growing earnings and sales support the shares over weeks to months."
    sources = [{"title": f"{f['form']} filed {f['date']}{' (earnings release)' if f.get('earnings') else ''}", "url": f["url"]} for f in filings[:3]]
    sources.append({"title": f"All {ticker} filings on EDGAR", "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={CIK[ticker]}&type=10-Q"})
    return Factor("sec_results", "Earnings", "Reported results (SEC filings)", detail, score=clamp(score), weight=0.8, sources=sources)


def recent_filings(sub: dict, cik: int) -> list[dict]:
    recent = sub.get("filings", {}).get("recent", {})
    out = []
    for form, day, acc, doc, items in zip(recent.get("form", []), recent.get("filingDate", []), recent.get("accessionNumber", []),
                                          recent.get("primaryDocument", []), recent.get("items", [""] * 10_000)):
        if form in ("10-Q", "10-K") or (form == "8-K" and "2.02" in (items or "")):
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
            out.append({"form": form, "date": day, "url": url, "earnings": form == "8-K"})
        if len(out) >= 3:
            break
    return out


async def sec_factors(ticker: str) -> tuple[list[Factor], list[str]]:
    cik = CIK.get(ticker)
    if cik is None:
        return [], []
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as http:
            facts, sub = await asyncio.gather(http.get(FACTS.format(cik=cik)), http.get(SUBMISSIONS.format(cik=cik)))
            facts.raise_for_status()
            sub.raise_for_status()
        factor = sec_factor(ticker, facts.json(), recent_filings(sub.json(), cik))
        return ([factor] if factor else []), []
    except Exception:
        return [], ["SEC EDGAR filings"]
