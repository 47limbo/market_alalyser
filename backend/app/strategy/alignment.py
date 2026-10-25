"""Stage 5: Timeframe Alignment, the entry for a ticker whose direction Stages 3 and 4 already set.

    Daily, 4H   bias      must agree with the niche direction
    1H, 15m     location  price at a discount, in a zone, swept liquidity or a higher low
    5m          trigger   the Entry Check setup: CHoCH or BOS with displacement, volume and a killzone

Aligned = bias agrees + at least one location + the trigger fired. Waiting = bias and location, no trigger yet.
Conflict = Daily or 4H trend runs against the direction: no trade, however good the 5m looks.
"""

from datetime import datetime

from ..detectors.sessions import NY, ny_time
from .calendar import Release, blackout

TIMEFRAMES = ["1d", "4h", "1h", "15m", "5m"]
ROLES = {"1d": "Bias", "4h": "Bias", "1h": "Location", "15m": "Location", "5m": "Trigger"}
NAMES = {"1d": "Daily", "4h": "4H", "1h": "1H", "15m": "15m", "5m": "5m"}
DEEP = 0.8  # past 80% of the 4H range is deep premium for a long (20% deep discount for a short)
RECENT = 40
CONFLICT_CAP = 15  # a conflict means no trade, so it can never score well


def _card(tf: str, status: str, trend: str | None, summary: str, checks: list[tuple[str, bool | None, str]]) -> dict:
    return {"tf": tf, "name": NAMES[tf], "role": ROLES[tf], "status": status, "trend": trend, "summary": summary,
            "checks": [{"label": l, "status": "n/a" if ok is None else "pass" if ok else "fail", "detail": d} for l, ok, d in checks]}


def _sma(candles: list[dict], n: int) -> float | None:
    return sum(k["c"] for k in candles[-n:]) / n if len(candles) >= n else None


def bias_card(tf: str, r: dict, side: str) -> dict:
    trend = r["trend"]
    last = r["candles"][-1]["c"]
    checks = [("Structure " + side, None if trend is None else trend == side, "" if trend == side else trend or "no break yet")]
    if tf == "1d":
        avg = _sma(r["candles"], 20)
        above = avg is not None and last > avg
        good = above if side == "bullish" else (avg is not None and last < avg)
        checks.append((f"Price {'above' if side == 'bullish' else 'below'} 20-day average", None if avg is None else good,
                       f"{last:,.2f} vs {avg:,.2f}" if avg else ""))
    else:
        dr = r.get("dealing_range")
        if dr:
            pos = dr["position"]
            stretched = pos > DEEP if side == "bullish" else pos < 1 - DEEP
            checks.append(("Not stretched in the range", not stretched, f"{dr['zone']}, {round(pos * 100)}% of range"))
    against = trend is not None and trend != side
    passed = all(c[1] for c in checks if c[1] is not None) and trend == side
    status = "conflict" if against else "pass" if passed else "wait"
    summary = {"conflict": f"Trend is {trend}, against the trade", "pass": f"{side.capitalize()} bias holds",
               "wait": "No clear bias yet"}[status]
    return _card(tf, status, trend, summary, checks)


def location_card(tf: str, r: dict, side: str) -> dict:
    candles = r["candles"]
    last = candles[-1]
    since = candles[max(0, len(candles) - RECENT)]["t"]
    checks = []
    if tf == "1h":
        dr = r.get("dealing_range")
        want = "discount" if side == "bullish" else "premium"
        checks.append((f"Price in {want}", None if not dr else dr["zone"] == want,
                       f"{dr['zone']}, {round(dr['position'] * 100)}% of range" if dr else "no range yet"))
        zones = [z for z in r["fvgs"] if z["direction"] == side and z["status"] in ("open", "partial")]
        zones += [b for b in r["order_blocks"] if b["direction"] == side and b["status"] == "active"]
        inside = next((z for z in zones if z["bottom"] <= last["c"] <= z["top"]), None)
        checks.append((f"Inside a {side} gap or order block", bool(inside),
                       f"{inside['bottom']:,.2f} to {inside['top']:,.2f}" if inside else "not in a zone"))
        v = r["vwap"][-1]["vwap"] if r.get("vwap") else None
        good = v is not None and (last["c"] > v if side == "bullish" else last["c"] < v)
        checks.append((f"Holding {'above' if side == 'bullish' else 'below'} VWAP", None if v is None else good,
                       f"VWAP {v:,.2f}" if v else ""))
    else:
        swept = [s for s in r["sweeps"] if s["direction"] == side and s["time"] >= since]
        checks.append((f"{'Sell' if side == 'bullish' else 'Buy'}-side liquidity swept", bool(swept),
                       f"{swept[-1]['source']} {swept[-1]['level']:,.2f}" if swept else f"none in the last {RECENT} candles"))
        kind = "low" if side == "bullish" else "high"
        pts = [s["price"] for s in r["swings"] if s["kind"] == kind][-2:]
        if len(pts) == 2:
            good = pts[1] > pts[0] if side == "bullish" else pts[1] < pts[0]
            checks.append((f"{'Higher low' if side == 'bullish' else 'Lower high'} formed", good, f"{pts[0]:,.2f} then {pts[1]:,.2f}"))
    ok = any(c[1] for c in checks)
    return _card(tf, "pass" if ok else "wait", r["trend"], "In location" if ok else "Not at a good price yet", checks)


def trigger_card(r: dict, direction: str) -> tuple[dict, dict | None]:
    setup = next((s for s in r["setups"] if s["direction"] == direction), None)
    if not setup:
        return _card("5m", "wait", r["trend"], "No setup", []), None
    by = {c["key"]: c for c in setup["checks"]}
    need = ["shift", "displacement", "volume", "killzone"]
    checks = [(by[k]["label"], None if by[k]["status"] == "n/a" else by[k]["status"] == "pass", by[k]["detail"]) for k in need if k in by]
    fired = setup["status"] in ("ready", "forming") and all(by.get(k, {}).get("status") == "pass" for k in need)
    if fired and setup["status"] == "ready":
        summary = "Triggered: price is back in the entry zone"
    elif fired:
        summary = "Triggered: waiting for the pullback into the zone"
    else:
        summary = {"none": "No trigger yet", "forming": "Setup forming, trigger incomplete", "ready": "In zone, trigger incomplete"}[setup["status"]]
    return _card("5m", "pass" if fired else "wait", r["trend"], summary, checks), setup


def position(entry: float, stop: float, target: float | None, amount: float, risk_pct: float) -> dict:
    """Size the trade so a stop-out loses at most risk_pct of the entry amount (the user's rule: $1000 in, $50 at risk)."""
    max_loss = amount * risk_pct / 100
    stop_pct = abs(entry - stop) / entry
    size = amount if stop_pct * amount <= max_loss else max_loss / stop_pct
    shares = int(size // entry)
    loss = shares * abs(entry - stop)
    gain = shares * abs(target - entry) if target is not None else None
    return {"amount": amount, "risk_pct": risk_pct, "max_loss": round(max_loss, 2), "stop_pct": round(stop_pct * 100, 2),
            "shares": shares, "notional": round(shares * entry, 2), "loss_at_stop": round(loss, 2),
            "gain_at_target": round(gain, 2) if gain is not None else None, "reduced": size < amount}


def session_warnings(now_ms: int, releases: list[Release], earnings_soon: str | None) -> list[str]:
    t = ny_time(now_ms)
    minutes = t.hour * 60 + t.minute
    out = []
    if t.weekday() >= 5:
        out.append("Weekend: the market is closed.")
    elif minutes < 9 * 60 + 35:
        out.append("Before 9:35 ET: no entries until 5 minutes after the open.")
    elif minutes >= 15 * 60 + 55:
        out.append("After 15:55 ET: be flat, no new day trades.")
    hit = blackout(releases, now_ms)
    if hit:
        out.append(f"{hit.title} at {datetime.fromtimestamp(hit.time / 1000, NY):%H:%M} ET: no entries 2 minutes before to 5 minutes after.")
    if earnings_soon:
        out.append(f"Earnings {earnings_soon}: day trade only, never hold through the report.")
    return out


def align(reports: dict[str, dict], direction: str, now_ms: int, releases: list[Release], amount: float = 1000,
          risk_pct: float = 5.0, niche_row: dict | None = None, candidate: dict | None = None) -> dict:
    side = "bullish" if direction == "long" else "bearish"
    cards = []
    for tf in ("1d", "4h"):
        if tf in reports:
            cards.append(bias_card(tf, reports[tf], side))
    for tf in ("1h", "15m"):
        if tf in reports:
            cards.append(location_card(tf, reports[tf], side))
    setup = None
    if "5m" in reports:
        card, setup = trigger_card(reports["5m"], direction)
        cards.append(card)

    by = {c["tf"]: c for c in cards}
    niche_dir = None
    if niche_row:
        niche_dir = "long" if niche_row["score"] >= 20 else "short" if niche_row["score"] <= -20 else None
    bias_ok = all(by.get(tf, {}).get("status") == "pass" for tf in ("1d", "4h"))
    conflict = any(by.get(tf, {}).get("status") == "conflict" for tf in ("1d", "4h")) or (niche_dir not in (None, direction))
    located = any(by.get(tf, {}).get("status") == "pass" for tf in ("1h", "15m"))
    triggered = by.get("5m", {}).get("status") == "pass"

    if conflict:
        verdict = "Conflict"
        why = ("The niche points the other way." if niche_dir not in (None, direction)
               else "The daily or 4H trend runs against the trade: no entry, however good the 5m looks.")
    elif bias_ok and located and triggered:
        verdict, why = "Aligned", "Bias, location and trigger agree."
    else:
        missing = [n for n, ok in (("bias", bias_ok), ("location", located), ("trigger", triggered)) if not ok]
        verdict, why = "Waiting", "Waiting for " + ", ".join(missing) + "."

    plan = None
    if setup and setup.get("entry") is not None and setup.get("stop") is not None:
        target = setup["targets"][0] if setup.get("targets") else None
        plan = {"entry": setup["entry"], "stop": setup["stop"], "target": target, "reward_risk": setup.get("reward_risk"),
                "size": position(setup["entry"], setup["stop"], target, amount, risk_pct)}

    alignment = sum(c["status"] == "pass" for c in cards) / len(TIMEFRAMES)
    niche_fit = 0.5
    if niche_row:
        niche_fit = max(0.0, niche_row["score"] / 100 * (1 if direction == "long" else -1))
    ticker_fit = candidate["fit"] if candidate else 0.5
    confidence = round(100 * niche_fit * ticker_fit * alignment)
    if verdict == "Conflict":
        confidence = min(confidence, CONFLICT_CAP)
    earnings = None
    if candidate:
        conf = next((c for c in candidate["checks"] if c["key"] == "conflict"), None)
        if conf and "earnings" in conf["detail"] and conf["status"] == "fail":
            earnings = conf["detail"]
    return {
        "direction": direction,
        "verdict": verdict,
        "why": why,
        "cards": cards,
        "plan": plan,
        "warnings": session_warnings(now_ms, releases, earnings),
        "confidence": confidence,
        "parts": {"niche": round(niche_fit, 2), "ticker": round(ticker_fit, 2), "alignment": round(alignment, 2)},
        "niche": niche_row,
    }
