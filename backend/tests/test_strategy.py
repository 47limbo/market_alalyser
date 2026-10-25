import asyncio
from datetime import datetime, timezone

from app.models import Candle
from app.strategy import score_log
from app.strategy.alignment import align, position
from app.strategy.board import build_board, read_for_regime
from app.strategy.calendar import blackout, classify, driver_surprises, number, parse_feed
from app.strategy.demo import demo_daily
from app.strategy.rules import SENSITIVITY, detect_regime, read
from app.strategy.shortlist import conflict_from, evaluate, shortlist
from app.strategy.universe import NICHES, niches_of

NOW = int(datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)


def test_every_niche_has_a_sensitivity_row():
    assert all(n.profile in SENSITIVITY for n in NICHES)
    assert [n.etf for n in niches_of("NVDA")] == ["XLK", "SMH"]


def test_calendar_numbers_and_surprise_signs():
    assert number("0.3%") == 0.3 and number("180K") == 180 and number("1.2M") == 1200 and number("") is None
    assert classify("Core CPI m/m")[0] == "cpi" and classify("Unemployment Claims")[2] == -1
    rows = [
        {"title": "Core CPI m/m", "country": "USD", "date": "2026-10-22T08:30:00-04:00", "impact": "High", "forecast": "0.3%", "previous": "0.3%", "actual": "0.5%"},
        {"title": "Unemployment Claims", "country": "USD", "date": "2026-10-22T08:30:00-04:00", "impact": "High", "forecast": "220K", "previous": "", "actual": "250K"},
        {"title": "Retail Sales m/m", "country": "USD", "date": "2026-10-23T08:30:00-04:00", "impact": "High", "forecast": "0.4%", "previous": "", "actual": ""},
        {"title": "German PMI", "country": "EUR", "date": "2026-10-22T04:30:00-04:00", "impact": "High", "forecast": "50", "previous": ""},
    ]
    rel = parse_feed(rows)
    assert [r.title for r in rel] == ["Core CPI m/m", "Unemployment Claims", "Retail Sales m/m"]
    assert rel[0].surprise == 2.0 and "hotter" in rel[0].note
    assert rel[1].surprise == -2.0 and "weaker" in rel[1].note  # more claims = weaker jobs
    assert rel[2].surprise is None and rel[2].note == "Not out yet."
    s = driver_surprises(rel, rel[0].time + 3_600_000)
    assert s["cpi"] > 1.9 and s["jobs"] < -1.9
    assert driver_surprises(rel, rel[0].time + 4 * 86_400_000) == {}
    assert blackout(rel, rel[0].time - 60_000) is rel[0] and blackout(rel, rel[0].time + 6 * 60_000) is None


def test_regime_and_read():
    assert detect_regime({"vix": 28}) == "risk_off"
    assert detect_regime({"vix": 16, "y10_5d": 20, "oil_5d": 5, "spy_above_20d": True}) == "inflation"
    assert detect_regime({"vix": 16, "y10_5d": -20, "copper_5d": -3, "spy_above_20d": True}) == "growth_scare"
    assert detect_regime({"vix": 16, "y10_5d": 0, "spy_above_20d": True}) == "risk_on"
    assert read(40, 30)[0] == "Confirmed bull" and read(40, -30)[0] == "Sell the news" and read(0, 30)[0] == "Tape only"
    # in an inflation scare strong jobs read as more inflation
    assert read_for_regime({"jobs": 1.0, "cpi": 0.5}, "inflation") == {"cpi": 1.5}


def test_board_replays_the_meta_capex_day():
    daily = demo_daily()
    board = build_board(daily, {}, [], NOW, {"META": ["Meta raises capex on AI spending"]})
    rows = {r["etf"]: r for r in board["rows"]}
    assert board["rows"][0]["etf"] == "XLV" and board["bull"][0] == "XLV"
    assert rows["XLC"]["score"] < -20 and "XLC" in board["bear"]
    meta = next(l for l in board["leaders"] if l["ticker"] == "META")
    assert meta["capex"] and meta["capex_niches"] == ["SMH", "XLU"]
    assert any("META spending" in x for x in rows["SMH"]["reasons"])
    assert board["rotation"] and "defensive" in board["rotation"]
    assert [r["rank"] for r in board["rows"]] == list(range(1, len(board["rows"]) + 1))


def test_shortlist_checks_and_conflicts():
    daily = demo_daily()
    board = build_board(daily, {}, [], NOW)
    groups = shortlist(board, daily)
    assert groups[0]["etf"] == "XLV" and groups[0]["direction"] == "long" and len(groups[0]["candidates"]) <= 3
    unh = evaluate("UNH", "XLV", "long", daily, board["leaders"], conflict_from("long", "2026-10-23 before the open", 1, []))
    assert not unh.qualifies and "earnings" in next(c for c in unh.checks if c.key == "conflict").detail
    assert conflict_from("long", None, None, [-0.6, -0.5, -0.8])["bad"]
    assert not conflict_from("short", None, None, [-0.6, -0.5, -0.8])["bad"]


def test_position_size_caps_the_loss():
    full = position(100.0, 98.0, 106.0, 1000, 5)  # 2% stop: $20 risk on $1000, under the $50 cap
    assert full["shares"] == 10 and not full["reduced"] and full["loss_at_stop"] == 20.0 and full["gain_at_target"] == 60.0
    cut = position(100.0, 90.0, None, 1000, 5)  # 10% stop: only $500 can go in
    assert cut["reduced"] and cut["shares"] == 5 and cut["loss_at_stop"] == 50.0


def _report(trend, zone="discount", pos=0.3, setup_status="none", trigger=False):
    candles = [{"t": i * 60_000, "o": 100, "h": 101, "l": 99, "c": 100 + i * 0.01} for i in range(60)]
    checks = [{"key": k, "label": k, "status": "pass" if trigger else "fail", "detail": ""} for k in ("shift", "displacement", "volume", "killzone")]
    return {"trend": trend, "candles": candles, "dealing_range": {"zone": zone, "position": pos}, "fvgs": [], "order_blocks": [],
            "vwap": [{"vwap": 99.0}], "sweeps": [], "swings": [],
            "setups": [{"direction": "long", "status": setup_status, "checks": checks, "entry": 100.0, "stop": 99.0, "targets": [103.0], "reward_risk": 3.0}]}


def test_alignment_verdicts():
    good = {tf: _report("bullish") for tf in ("1d", "4h", "1h", "15m")}
    good["5m"] = _report("bullish", setup_status="ready", trigger=True)
    niche = {"etf": "XLV", "name": "Healthcare", "score": 60, "label": "Strong bull", "read": "Confirmed bull"}
    a = align(good, "long", NOW, [], niche_row=niche)
    assert a["verdict"] == "Aligned" and a["plan"]["size"]["shares"] == 10
    waiting = dict(good, **{"5m": _report("bullish")})
    assert align(waiting, "long", NOW, [], niche_row=niche)["verdict"] == "Waiting"
    against = dict(good, **{"4h": _report("bearish")})
    c = align(against, "long", NOW, [], niche_row=niche)
    assert c["verdict"] == "Conflict" and c["confidence"] <= 15
    assert align(good, "short", NOW, [], niche_row=niche)["verdict"] == "Conflict"  # niche points the other way


def test_prediction_log_scoring():
    day = 86_400_000
    t0 = int(datetime(2026, 10, 19, 20, tzinfo=timezone.utc).timestamp() * 1000)
    spy = [Candle(t0 + i * day, 100, 100, 100, c, 1) for i, c in enumerate([100, 101, 102])]
    up = [Candle(t0 + i * day, 50, 50, 50, c, 1) for i, c in enumerate([50, 50, 52])]  # beats SPY on day 2
    log = {"2026-10-20": {"XLV": 1, "XLK": -1}}
    got = score_log(log, {"SPY": spy, "XLV": up, "XLK": up}, "2026-10-22")
    assert got["total"] == 2 and got["right"] == 1


def test_load_charts_stocks_from_yahoo_first(monkeypatch):
    import app.main as m

    calls = []

    async def yahoo_fetch(symbol, interval, limit, **kw):
        calls.append(("yahoo", symbol))
        return [Candle(0, 1, 1, 1, 1, 1)]

    async def hl_fetch(coin, interval, limit):
        calls.append(("hl", coin))
        return [Candle(0, 1, 1, 1, 1, 1)]

    monkeypatch.setattr(m, "DEMO", False)
    monkeypatch.setattr(m.yahoo, "fetch_candles", yahoo_fetch)
    monkeypatch.setattr(m, "fetch_candles", hl_fetch)
    assert asyncio.run(m.load("NVDA", "15m", 10))[1] == "yahoo"
    assert asyncio.run(m.load("BTC", "15m", 10))[1] == "hyperliquid"
    assert asyncio.run(m.load("UNH", "5m", 10))[1] == "yahoo" and m.resolve("UNH").kind == "stock"
    assert calls == [("yahoo", "NVDA"), ("hl", "BTC"), ("yahoo", "UNH")]
