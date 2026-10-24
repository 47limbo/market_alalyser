from datetime import date

from app.context.confidence import context_bias, score_setup
from app.context.earnings import earnings_factors
from app.context.factor import Factor
from app.context.feeds import parse_fred_csv, parse_rss
from app.context.macro import fomc_factor, rate_factors
from app.context.news import headline_factor, tone
from app.context.research import parse_brief
from app.models import Candle
from app.watchlist import WATCHLIST, find
from app.yahoo import parse_chart, resample

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Nvidia beats estimates, raises guidance - Reuters</title><link>https://example.com/a</link>
<pubDate>Fri, 23 Oct 2026 14:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Chip stocks slump on export controls</title><link>https://example.com/b</link></item>
</channel></rss>"""


def series(*values):
    return [(f"2026-01-{i + 1:02d}", v) for i, v in enumerate(values)]


def test_watchlist_maps_every_ticker():
    assert [a.ticker for a in WATCHLIST] == ["NVDA", "TSLA", "AAPL", "AMD", "MSFT", "AMZN", "META", "PLTR", "GOOGL", "SPY", "QQQ", "IWM", "BTC", "SOL"]
    assert find("spy").coin == "mkts:US500" and find("xyz:NVDA").ticker == "NVDA" and find("ETH") is None


def test_parse_rss_and_fred():
    items = parse_rss(RSS)
    assert items[0]["title"] == "Nvidia beats estimates, raises guidance" and items[0]["source"] == "Reuters"
    assert items[0]["published"] == 1792764000000 and items[1]["published"] is None
    assert parse_fred_csv("DATE,DGS10\n2026-01-01,4.1\n2026-01-02,.\n2026-01-05,4.2\n") == [("2026-01-01", 4.1), ("2026-01-05", 4.2)]


def test_headline_tone():
    assert tone("Nvidia beats estimates, raises guidance") > 0.5
    assert tone("Chip stocks slump on export controls") < -0.5
    assert tone("Fed signals rate cut") > 0 and tone("Fed signals rate hike") < 0
    assert tone("Apple to hold event on Tuesday") == 0
    f = headline_factor("news", "News", "x", parse_rss(RSS), 1.0)
    assert f.sources[0]["tone"] != 0 and abs(f.score) < 0.5  # two headlines are weak evidence


def test_rising_yields_and_high_vix_are_headwinds():
    rising = rate_factors({"DGS10": series(*[4.0] * 20, 4.4), "VIXCLS": series(28.0)}, "stock")
    assert all(f.score < 0 for f in rising)
    falling = rate_factors({"DGS10": series(*[4.4] * 20, 4.0), "VIXCLS": series(13.0)}, "stock")
    assert all(f.score > 0 for f in falling)


def test_fomc_risk_rises_into_the_decision():
    assert fomc_factor(date(2026, 10, 27), []).risk == 1.0
    assert fomc_factor(date(2026, 10, 24), []).risk == 0.25  # four days out
    assert fomc_factor(date(2026, 11, 2), []).risk == 0.0
    assert "Dec" in fomc_factor(date(2026, 11, 2), []).detail


def test_earnings_soon_is_a_risk_and_beats_are_bullish():
    cal = [{"date": "2026-10-26", "hour": "amc", "epsEstimate": 1.2}]
    hist = [{"actual": 1.3, "estimate": 1.2, "period": "2026-06-30"}, {"actual": 1.1, "estimate": 1.0}]
    nxt, eps = earnings_factors("NVDA", date(2026, 10, 24), cal, hist)
    assert nxt.risk == 0.7 and "after the close" in nxt.detail
    assert eps.score > 0


def test_confidence_blends_chart_and_context():
    long = {"direction": "long", "status": "ready", "score": 8, "max_score": 10}
    short = dict(long, direction="short")
    bullish = [Factor("a", "g", "a", "", score=0.8), Factor("b", "g", "b", "", score=0.4)]
    assert context_bias(bullish) > 0
    hi, lo = score_setup(long, bullish), score_setup(short, bullish)
    assert hi["confidence"] > lo["confidence"] and hi["chart_points"] == 48.0
    assert hi["reasons"][0]["effect"] == "supports" and lo["reasons"][0]["effect"] == "against"
    risky = score_setup(long, bullish + [Factor("fomc", "Fed", "Fed", "", risk=1.0)])
    assert risky["confidence"] == hi["confidence"] - 25 and risky["reasons"][0]["effect"] == "risk"


def test_parse_brief_takes_the_last_json_block():
    text = 'I searched.\n```json\n{"bias": "x"}\n```\nThen:\n```json\n{"bias": "bullish", "strength": 60}\n```'
    assert parse_brief(text) == {"bias": "bullish", "strength": 60}


def test_yahoo_parse_and_4h_resample():
    data = {"chart": {"result": [{"timestamp": [0, 3600, 7200, 14400],
            "indicators": {"quote": [{"open": [1, 2, None, 4], "high": [2, 3, None, 5], "low": [0.5, 1, None, 3], "close": [2, 3, None, 4.5], "volume": [10, 20, None, 5]}]}}]}}
    candles = parse_chart(data)
    assert len(candles) == 3 and candles[0] == Candle(0, 1, 2, 0.5, 2, 10)
    four = resample(candles, 4 * 3_600_000)
    assert four[0] == Candle(0, 1, 3, 0.5, 3, 30) and four[1].t == 14_400_000


def test_yahoo_earnings_rows():
    from datetime import datetime

    from app.context.earnings import yahoo_rows
    rows = [(datetime(2026, 11, 19, 16, 0), 1.25, None), (datetime(2026, 8, 27, 16, 0), 1.0, 1.05), (datetime(2026, 5, 28, 16, 0), 0.9, 0.96)]
    cal, hist = yahoo_rows(rows, date(2026, 10, 24))
    assert cal == [{"date": "2026-11-19", "hour": "amc", "epsEstimate": 1.25}]
    assert hist[0]["actual"] == 1.05 and hist[0]["period"] == "Reported 27 Aug 2026"
    nxt, eps = earnings_factors("NVDA", date(2026, 10, 24), cal, hist, {"title": "Yahoo", "url": "https://finance.yahoo.com"})
    assert nxt.risk == 0 and eps.score > 0 and eps.sources[0]["title"] == "Yahoo"


def test_sec_results_from_filings():
    from app.context.sec import recent_filings, sec_factor
    facts = {"facts": {"us-gaap": {
        "EarningsPerShareDiluted": {"units": {"USD/shares": [
            {"frame": "CY2025Q2", "val": 0.5}, {"frame": "CY2026Q2", "val": 0.75}, {"frame": "CY2025", "val": 2.0}, {"val": 9}]}},
        "Revenues": {"units": {"USD": [{"frame": "CY2025Q2", "val": 10e9}, {"frame": "CY2026Q2", "val": 12e9}]}},
    }}}
    sub = {"filings": {"recent": {"form": ["4", "8-K", "8-K", "10-Q"], "filingDate": ["2026-09-01", "2026-08-28", "2026-08-27", "2026-08-26"],
           "accessionNumber": ["a", "0001-26-1", "0001-26-2", "0001-26-3"], "primaryDocument": ["x", "pr.htm", "other.htm", "q.htm"],
           "items": ["", "2.02,9.01", "5.02", ""]}}}
    filings = recent_filings(sub, 1045810)
    assert [f["form"] for f in filings] == ["8-K", "10-Q"] and filings[0]["url"].endswith("/1045810/0001261/pr.htm")
    f = sec_factor("NVDA", facts, filings)
    assert "Q2 2026" in f.detail and "+50%" in f.detail and "$12.0bn (+20%)" in f.detail and f.score > 0.5
    assert f.sources[0]["title"] == "8-K filed 2026-08-28 (earnings release)"


def test_headlines_must_name_the_asset():
    from app.context.news import mentions
    amd = find("AMD").keywords
    assert mentions("AMD jumps on new AI chip deal", amd) and mentions("Advanced Micro Devices beats estimates", amd)
    assert not mentions("Amdocs shares slide", amd) and not mentions("Nvidia hits record high", amd)
    assert not mentions("Metal prices climb", find("META").keywords)
