"""Entry Check: the setup model from Part 3.2 of the research doc.

For each direction it walks the checklist on the latest candles and, when a setup exists,
proposes an entry zone, stop, targets and reward to risk. This is analysis only:
the app shows the setup and never places an order.
"""

from dataclasses import dataclass, field

from .detectors.liquidity import LiquidityLevel, Sweep
from .detectors.sessions import killzone_for
from .detectors.structure import StructureEvent
from .detectors.zones import FairValueGap, OrderBlock
from .models import Candle

HIGHER_TIMEFRAME = {
    "1m": "15m",
    "3m": "1h",
    "5m": "1h",
    "15m": "4h",
    "30m": "4h",
    "1h": "1d",
    "2h": "1d",
    "4h": "1d",
}


@dataclass
class Check:
    key: str
    label: str
    status: str  # "pass", "fail" or "n/a"
    detail: str = ""


@dataclass
class Setup:
    direction: str  # "long" or "short"
    status: str  # "ready" (price in the entry zone), "forming" (waiting for the retrace) or "none"
    checks: list[Check] = field(default_factory=list)
    score: int = 0
    max_score: int = 0
    entry: float | None = None
    zone_top: float | None = None
    zone_bottom: float | None = None
    zone_kind: str | None = None
    zone_time_index: int | None = None
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    reward_risk: float | None = None
    sweep_index: int | None = None
    shift_index: int | None = None


def evaluate_setups(
    candles: list[Candle],
    atrs: list[float],
    rvol: list[float | None],
    vwap: list[dict],
    events: list[StructureEvent],
    sweeps: list[Sweep],
    fvgs: list[FairValueGap],
    blocks: list[OrderBlock],
    levels: list[LiquidityLevel],
    dealing: dict | None,
    htf_trend: str | None,
    window: int = 40,
    min_rr: float = 2.0,
    stop_buffer_atr: float = 0.1,
) -> list[Setup]:
    return [
        _evaluate(d, candles, atrs, rvol, vwap, events, sweeps, fvgs, blocks, levels, dealing, htf_trend,
                  window, min_rr, stop_buffer_atr)
        for d in ("long", "short")
    ]


def _evaluate(direction, candles, atrs, rvol, vwap, events, sweeps, fvgs, blocks, levels, dealing, htf_trend,
              window, min_rr, stop_buffer_atr) -> Setup:
    bull = direction == "long"
    side = "bullish" if bull else "bearish"
    last_i = len(candles) - 1
    last = candles[-1]
    setup = Setup(direction, "none")
    add = setup.checks.append

    # 1. higher-timeframe bias
    if htf_trend is None:
        add(Check("htf", "Higher-timeframe bias agrees", "n/a", "no higher-timeframe break yet"))
    else:
        add(Check("htf", "Higher-timeframe bias agrees", "pass" if htf_trend == side else "fail",
                  f"higher timeframe is {htf_trend}"))

    # 2. premium / discount
    if dealing is None:
        add(Check("pd", "Price in discount" if bull else "Price in premium", "n/a", "no dealing range yet"))
    else:
        want = "discount" if bull else "premium"
        add(Check("pd", f"Price in {want}", "pass" if dealing["zone"] == want else "fail",
                  f"{dealing['zone']}, {round(dealing['position'] * 100)}% of range"))

    # 3. liquidity sweep against the trade, within the window
    recent = [s for s in sweeps if s.direction == side and s.confirmed_at >= last_i - window]
    sweep = recent[-1] if recent else None
    add(Check("sweep", "Sell-side liquidity swept" if bull else "Buy-side liquidity swept",
              "pass" if sweep else "fail",
              f"{sweep.source} {sweep.level:g} taken" if sweep else f"none in the last {window} candles"))

    # 4. structure shift after the sweep, 5. with displacement
    shift = None
    if sweep:
        shift = next((e for e in events if e.direction == side and e.index >= sweep.index), None)
    add(Check("shift", "CHoCH or BOS after the sweep", "pass" if shift else "fail",
              f"{shift.type} at {shift.level:g}" if shift else "no break yet"))
    add(Check("displacement", "Break came with displacement", "pass" if shift and shift.displacement else "fail"))

    # 6. an entry zone left by the move
    zone = _entry_zone(side, sweep, fvgs, blocks)
    if zone:
        kind, top, bottom, idx = zone
        setup.zone_kind, setup.zone_top, setup.zone_bottom, setup.zone_time_index = kind, top, bottom, idx
        setup.entry = (top + bottom) / 2
    add(Check("zone", "Fair value gap or order block to enter from", "pass" if zone else "fail",
              f"{zone[0]} {zone[2]:g} to {zone[1]:g}" if zone else "no live zone since the sweep"))

    # 7. price back in the zone
    # the candles that form the zone cannot count as the pullback into it
    in_zone = (bool(zone) and last_i > setup.zone_time_index + 1
               and last.l <= setup.zone_top and last.h >= setup.zone_bottom)
    add(Check("retrace", "Price retraced into the zone", "pass" if in_zone else "fail",
              "" if in_zone else "waiting for the pullback" if zone else ""))

    # 8. session timing
    kz = killzone_for(last.t)
    add(Check("killzone", "Inside a killzone", "pass" if kz else "fail", kz or "outside killzones"))

    # 9. participation on the break
    rv = rvol[shift.index] if shift else None
    if rv is None:
        add(Check("volume", "Volume above average on the break", "n/a" if not shift else "fail",
                  "" if not shift else "not enough history"))
    else:
        add(Check("volume", "Volume above average on the break", "pass" if rv >= 1.5 else "fail", f"{rv:.1f}x"))

    # 10. VWAP side
    v = vwap[-1]["vwap"]
    add(Check("vwap", "Price above VWAP" if bull else "Price below VWAP",
              "pass" if (last.c > v if bull else last.c < v) else "fail", f"VWAP {v:,.2f}"))

    # risk plan: stop beyond the sweep, targets at the next opposing liquidity
    if sweep and setup.entry is not None:
        buffer = stop_buffer_atr * atrs[-1]
        setup.stop = sweep.extreme - buffer if bull else sweep.extreme + buffer
        setup.sweep_index = sweep.index
        risk = setup.entry - setup.stop if bull else setup.stop - setup.entry
        targets = sorted(
            {lv.price for lv in levels
             if lv.swept_at is None and lv.kind == ("buy-side" if bull else "sell-side")
             and (lv.price > setup.entry if bull else lv.price < setup.entry)},
            reverse=not bull,
        )
        setup.targets = targets[:2]
        if risk > 0 and setup.targets:
            setup.reward_risk = round(abs(setup.targets[0] - setup.entry) / risk, 2)
    if shift:
        setup.shift_index = shift.index
    rr_ok = setup.reward_risk is not None and setup.reward_risk >= min_rr
    add(Check("rr", f"Reward to risk at least {min_rr:g}R", "pass" if rr_ok else "fail",
              f"{setup.reward_risk:g}R" if setup.reward_risk is not None else "no target or stop yet"))

    scored = [c for c in setup.checks if c.status != "n/a"]
    setup.max_score = len(scored)
    setup.score = sum(c.status == "pass" for c in scored)

    core = sweep and shift and zone and rr_ok
    if core and _still_valid(setup, candles, bull):
        setup.status = "ready" if in_zone else "forming"
    return setup


def _entry_zone(side, sweep, fvgs, blocks):
    """Most recent live FVG in the trade direction since the sweep, else the most recent active order block."""
    if not sweep:
        return None
    gaps = [g for g in fvgs if g.direction == side and g.index >= sweep.index and g.status in ("open", "partial")]
    if gaps:
        g = gaps[-1]
        return ("fair value gap", g.top, g.bottom, g.index)
    obs = [b for b in blocks if b.direction == side and b.index >= sweep.index - 5 and b.status != "breaker"]
    if obs:
        b = obs[-1]
        return ("order block", b.top, b.bottom, b.index)
    return None


def _still_valid(setup: Setup, candles: list[Candle], bull: bool) -> bool:
    """Invalidated once any candle after the sweep closes beyond the stop."""
    for k in candles[setup.sweep_index + 1 :]:
        if (k.c < setup.stop) if bull else (k.c > setup.stop):
            return False
    return True
