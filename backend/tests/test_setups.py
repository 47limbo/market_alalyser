from app.analyze import analyse
from tests.test_detectors import bars, flat

# sell-side sweep of a swing low, then a bullish break with displacement that leaves a gap,
# then a pullback into the gap, with untouched buy-side liquidity at 120 as the target
SCENARIO = (
    flat(100, 5)
    + [(100, 120, 99, 108), (108, 112, 103, 104), (104, 104.5, 100, 101), (101, 101.5, 97, 98)]
    + [(98, 98.5, 95, 96)]  # swing low 95 (index 9)
    + [(96, 99, 96, 98.5), (98.5, 100.5, 97, 98), (98, 99, 97, 98.5), (98.5, 99, 97.2, 98)]
    + [(98, 99, 93.5, 97)]  # wick below 95, close back above: sweep (index 14)
    + [(97, 98, 96.5, 97.5)]
    + [(97.5, 105, 97.4, 104.9)]  # displacement through the 100.5 swing high
    + [(104.9, 106, 103.5, 105.5)]  # leaves a gap 98 to 103.5
    + [(105.5, 105.8, 101, 101.5)]  # pulls back into the gap
)


def long_setup(report):
    return next(s for s in report["setups"] if s["direction"] == "long")


def test_long_setup_ready_with_risk_plan():
    r = analyse(bars(SCENARIO), swing_lookback=2)
    s = long_setup(r)
    checks = {c["key"]: c["status"] for c in s["checks"]}
    assert checks["sweep"] == checks["shift"] == checks["displacement"] == checks["zone"] == "pass"
    assert checks["retrace"] == "pass" and checks["rr"] == "pass"
    assert s["status"] == "ready"
    assert s["zone_kind"] == "fair value gap" and (s["zone_bottom"], s["zone_top"]) == (98, 103.5)
    assert s["entry"] == 100.75
    assert s["stop"] < 93.5
    assert s["targets"][0] == 120
    assert s["reward_risk"] >= 2


def test_setup_is_forming_before_the_pullback():
    r = analyse(bars(SCENARIO[:-1]), swing_lookback=2)
    assert long_setup(r)["status"] == "forming"


def test_setup_invalidated_by_close_below_stop():
    r = analyse(bars(SCENARIO + [(101.5, 101.5, 90, 90.5)]), swing_lookback=2)
    assert long_setup(r)["status"] == "none"


def test_short_side_has_no_setup_here():
    r = analyse(bars(SCENARIO), swing_lookback=2)
    short = next(s for s in r["setups"] if s["direction"] == "short")
    assert short["status"] == "none"
