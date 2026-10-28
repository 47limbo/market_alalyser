import pytest
from pydantic import ValidationError

from app.positions import DEFAULTS, Position, load_positions, parse_hyperliquid_ctxs, parse_yahoo_quote, save_positions


def test_defaults_until_saved_then_round_trip(tmp_path):
    f = tmp_path / "positions.json"
    assert [p.symbol for p in load_positions(f)] == [p.symbol for p in DEFAULTS]
    held = [Position(symbol=" pld ", qty=-50, cost=128.14), Position(symbol="ondo", kind="crypto", qty=12500, cost=0.43)]
    save_positions(held, f)
    back = load_positions(f)
    assert [(p.symbol, p.kind, p.qty) for p in back] == [("PLD", "stock", -50), ("ONDO", "crypto", 12500)]
    f.write_text("not json")
    assert len(load_positions(f)) == len(DEFAULTS)


def test_rejects_bad_rows():
    for bad in ({"symbol": "X", "qty": 0, "cost": 1}, {"symbol": "X", "qty": 1, "cost": 0},
                {"symbol": "X", "qty": 1, "cost": 1, "kind": "bond"}, {"symbol": "", "qty": 1, "cost": 1}):
        with pytest.raises(ValidationError):
            Position(**bad)


def test_yahoo_quote_with_after_hours_trade():
    data = {"chart": {"result": [{
        "meta": {"regularMarketPrice": 217.21, "chartPreviousClose": 217.94,
                 "currentTradingPeriod": {"regular": {"start": 1000, "end": 2000}}},
        "timestamp": [1500, 1990, 2100],
        "indicators": {"quote": [{"close": [217.0, 217.21, 218.4]}]},
    }]}}
    q = parse_yahoo_quote(data)
    assert q["price"] == 217.21 and q["prev_close"] == 217.94 and q["ext_price"] == 218.4
    data["chart"]["result"][0]["timestamp"][-1] = 1995  # last trade inside the session: no extended price
    assert parse_yahoo_quote(data)["ext_price"] is None


def test_hyperliquid_marks():
    data = [{"universe": [{"name": "SOL"}, {"name": "ONDO"}]},
            [{"markPx": "100.98", "prevDayPx": "99.5"}, {"markPx": "0.4138", "prevDayPx": None}]]
    q = parse_hyperliquid_ctxs(data)
    assert q["SOL"]["price"] == 100.98 and q["SOL"]["prev_close"] == 99.5 and q["ONDO"]["prev_close"] is None
