from app.analyze import analyse
from app.demo import demo_candles
from app.detectors.indicators import atr
from app.detectors.liquidity import detect_liquidity
from app.detectors.structure import detect_structure, find_swings
from app.detectors.volume import session_vwap, volume_profile
from app.detectors.zones import dealing_range, detect_fvgs, detect_order_blocks
from app.models import Candle

H = 3_600_000


def bars(rows, start=1_700_000_000_000, step=H):
    """rows of (o, h, l, c) or (o, h, l, c, v)"""
    out = []
    for i, r in enumerate(rows):
        o, h, l, c, *v = r
        out.append(Candle(start + i * step, o, h, l, c, v[0] if v else 1.0))
    return out


def flat(price, n):
    return [(price, price + 1, price - 1, price)] * n


def test_swing_high_and_low_need_strictly_higher_and_lower_neighbours():
    c = bars([(10, 11, 9, 10), (10, 12, 9, 11), (11, 15, 10, 14), (14, 13.5, 8, 9), (9, 10, 5, 6), (6, 9, 7, 8), (8, 9, 7, 8)])
    swings = find_swings(c, lookback=2)
    assert [(s.kind, s.index, s.price) for s in swings] == [("high", 2, 15), ("low", 4, 5)]
    assert swings[0].confirmed_at == 4


def test_bos_then_choch():
    rows = (
        flat(100, 3)
        + [(100, 110, 99, 109), (109, 109.5, 103, 104)]  # swing high 110 at index 3
        + flat(104, 3)
        + [(104, 115, 104, 114)]  # close 114 above 110 -> bullish BOS
        + [(114, 114.5, 112, 113), (113, 113.5, 105, 106)]  # pull back to form a swing low
        + [(106, 108, 102, 107)]  # swing low 102 at index 11
        + flat(107, 3)
        + [(107, 107.5, 95, 96)]  # close below 102 -> bearish CHoCH
    )
    c = bars(rows)
    res = detect_structure(c, atr(c), lookback=2)
    kinds = [(e.type, e.direction, e.level) for e in res.events]
    assert ("BOS", "bullish", 110) in kinds
    assert kinds[-1] == ("CHoCH", "bearish", 102)
    assert res.trend == "bearish"


def test_bullish_fvg_detected_and_tracked_to_inversion():
    rows = flat(100, 15) + [
        (100, 101, 99, 100.5),  # candle 1: high 101
        (100.5, 110, 100.5, 109.5),  # impulse
        (109.5, 112, 105, 111),  # candle 3: low 105 -> gap 101..105
        (111, 111.5, 103, 104),  # dips into the gap (50%)
        (104, 104.5, 98, 99),  # closes below 101 -> inverted
    ]
    c = bars(rows)
    gaps = [g for g in detect_fvgs(c, atr(c)) if g.direction == "bullish"]
    g = gaps[0]
    assert (g.bottom, g.top, g.index) == (101, 105, 16)
    assert g.status == "inverted"
    assert g.touched_at == 18 and g.filled_at == 19


def test_small_gaps_are_ignored():
    rows = flat(100, 15) + [(100, 101, 99, 100.5), (100.5, 101.2, 100.4, 101.1), (101.1, 101.5, 101.05, 101.4)]
    c = bars(rows)
    assert detect_fvgs(c, atr(c), min_atr_mult=0.25) == []


def test_order_block_is_last_down_candle_before_displacement():
    rows = (
        flat(100, 3)
        + [(100, 104, 99, 103), (103, 103.5, 100.5, 101)]  # swing high 104 at index 3
        + flat(101, 2)
        + [(101, 101.5, 98.5, 99)]  # down candle at the low -> order block (index 7)
        + [(99, 108, 99, 107.8)]  # displacement up, closes above 104 -> BOS
        + [(107.8, 108.5, 106, 107)] * 3
        + [(107, 107.2, 101, 101.2)]  # trades back into the block
    )
    c = bars(rows)
    a = atr(c)
    st = detect_structure(c, a, lookback=2)
    ev = [e for e in st.events if e.direction == "bullish"][0]
    assert ev.displacement
    obs = detect_order_blocks(c, a, st.events)
    ob = [b for b in obs if b.direction == "bullish"][0]
    assert ob.index == 7 and (ob.bottom, ob.top) == (98.5, 101.5)
    assert ob.status == "mitigated" and ob.mitigated_at == 12


def test_sweep_vs_break_of_liquidity():
    rows = (
        flat(100, 3)
        + [(100, 105, 99, 101)]  # swing high 105 at index 3
        + flat(101, 3)
        + [(101, 106, 100, 102)]  # wick above 105, close back below -> sweep
        + flat(101, 3)
        + [(101, 101.5, 95, 100)]  # swing low 95 at index 11
        + flat(100, 3)
        + [(100, 100, 90, 91)]  # closes below 95 and stays -> break
        + [(91, 92, 89, 90)] * 3
    )
    c = bars(rows)
    a = atr(c)
    swings = find_swings(c, lookback=2)
    res = detect_liquidity(c, swings, a, include_reference_levels=False)
    high = next(lv for lv in res.levels if lv.source == "swing" and lv.price == 105)
    low = next(lv for lv in res.levels if lv.source == "swing" and lv.price == 95)
    assert high.sweep_type == "sweep" and high.swept_at == 7
    assert low.sweep_type == "break"
    assert [(s.direction, s.level) for s in res.sweeps] == [("bearish", 105)]


def test_equal_highs_are_flagged():
    rows = flat(100, 3) + [(100, 110, 99, 101)] + flat(101, 3) + [(101, 110.02, 100, 101)] + flat(101, 3)
    c = bars(rows)
    res = detect_liquidity(c, find_swings(c, 2), atr(c), include_reference_levels=False)
    assert any(lv.source == "equal highs" and lv.price == 110.02 for lv in res.levels)


def test_dealing_range_zones():
    c = bars(flat(100, 3) + [(100, 120, 99, 110)] + flat(110, 3) + [(110, 111, 80, 90)] + flat(90, 3))
    swings = find_swings(c, 2)
    dr = dealing_range(c, swings, trend="bullish")
    assert dr["high"] == 120 and dr["low"] == 80 and dr["equilibrium"] == 100
    assert dr["zone"] == "discount"
    assert abs(dr["ote_low"] - 88.4) < 1e-9 and abs(dr["ote_high"] - 95.2) < 1e-9
    assert dr["in_ote"]


def test_vwap_and_profile():
    c = bars([(10, 11, 9, 10, 1), (10, 21, 19, 20, 3)])
    v = session_vwap(c)
    assert v[-1]["vwap"] == (10 * 1 + 20 * 3) / 4
    p = volume_profile(bars([(10, 10.5, 9.5, 10, 100)] * 5 + [(14, 15, 13, 14, 1)]), bins=10)
    assert p["val"] <= p["poc"] <= p["vah"] and p["poc"] < 11


def test_dealing_range_stretches_to_new_extremes():
    c = bars(flat(100, 3) + [(100, 120, 99, 110)] + flat(110, 3) + [(110, 111, 80, 90)] + flat(90, 3) + [(90, 90, 70, 72)])
    dr = dealing_range(c, find_swings(c, 2), trend="bearish")
    assert dr["low"] == 70 and 0 <= dr["position"] <= 1


def test_full_report_has_no_lookahead():
    """Analysing a prefix must give the same events as the full series up to that point."""
    full = demo_candles(count=400)
    a_full = analyse(full)
    a_part = analyse(full[:300])
    ev_full = [(e["type"], e["index"]) for e in a_full["structure"] if e["index"] < 300]
    ev_part = [(e["type"], e["index"]) for e in a_part["structure"]]
    assert ev_full == ev_part
