"""Small fetch-and-parse helpers for the free public sources the context layer reads.

Every fetch is read-only and returns plain dicts. Callers treat any failure as "source unavailable".
"""

import csv
import html
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) MarketAnalyser/1.0"}
TIMEOUT = 10


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)


def parse_rss(text: str, limit: int = 30) -> list[dict]:
    """Items of an RSS 2.0 feed as {title, url, source, published (ms), summary}; Google News puts the outlet in <source>."""
    root = ET.fromstring(text)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source = (item.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        published = None
        if item.findtext("pubDate"):
            try:
                published = int(parsedate_to_datetime(item.findtext("pubDate")).timestamp() * 1000)
            except (TypeError, ValueError):
                pass
        summary = clean_text(item.findtext("description") or "")
        # Google News' description only repeats the headline and outlet, so it is no summary
        if len(summary) < 40 or summary.startswith(title[:30]):
            summary = ""
        items.append({"title": title, "url": (item.findtext("link") or "").strip(), "source": source,
                      "published": published, "summary": summary})
        if len(items) >= limit:
            break
    return items


def clean_text(raw: str, limit: int = 320) -> str:
    """Plain text from an HTML snippet, cut at a word boundary."""
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw))).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


_META = [re.compile(rf'<meta[^>]+(?:property|name)=["\']{name}["\'][^>]*>', re.I) for name in ("og:description", "description", "twitter:description")]
_CONTENT = re.compile(r'content=["\']([^"\']+)["\']', re.I)


def meta_description(page: str) -> str:
    """The summary a publisher puts in the page's meta tags for link previews."""
    head = page[:200_000]
    for pattern in _META:
        tag = pattern.search(head)
        if tag and (content := _CONTENT.search(tag.group(0))):
            text = clean_text(content.group(1))
            if len(text) >= 40:
                return text
    return ""


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    """FRED's graph CSV as (date, value) pairs, skipping the '.' FRED uses for missing days."""
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for row in rows[1:]:
        if len(row) >= 2:
            try:
                out.append((row[0], float(row[1])))
            except ValueError:
                continue
    return out


async def get_text(http: httpx.AsyncClient, url: str, **params) -> str:
    resp = await http.get(url, params=params or None)
    resp.raise_for_status()
    return resp.text


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)
