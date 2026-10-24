"""Blend the chart's Entry Check with the news and macro context into one confidence number per direction.

    confidence = 60% chart (checks passed) + 40% context (how far the evidence leans the same way)
                 - up to 25 points for event risk (earnings, a Fed decision) in the next few days
                 capped at 40 when the chart has no setup

The chart decides where and when; context decides how much to trust it. A score is a summary, not a
signal: read the reasons underneath it.
"""

from .factor import Factor

CHART_WEIGHT = 0.6
MAX_EVENT_PENALTY = 25
NO_SETUP_CAP = 40


def context_bias(factors: list[Factor]) -> float:
    """Weighted mean of the directional factors, -1 (bearish) to +1 (bullish)."""
    directional = [f for f in factors if f.weight > 0 and not f.risk]
    total = sum(f.weight for f in directional)
    return sum(f.score * f.weight for f in directional) / total if total else 0.0


def bias_label(bias: float) -> str:
    if abs(bias) < 0.1:
        return "neutral"
    side = "bullish" if bias > 0 else "bearish"
    return f"strongly {side}" if abs(bias) >= 0.4 else f"leaning {side}"


def grade(score: float) -> str:
    return "high" if score >= 70 else "medium" if score >= 50 else "low"


def score_setup(setup: dict, factors: list[Factor]) -> dict:
    sign = 1 if setup["direction"] == "long" else -1
    chart = setup["score"] / setup["max_score"] if setup.get("max_score") else 0.0
    aligned = context_bias(factors) * sign
    # several events stack, but never past the full penalty
    calm = 1.0
    for f in factors:
        calm *= 1 - f.risk
    risk = 1 - calm
    chart_pts = 100 * CHART_WEIGHT * chart
    context_pts = 100 * (1 - CHART_WEIGHT) * (aligned + 1) / 2
    penalty = MAX_EVENT_PENALTY * risk
    total = max(0.0, min(100.0, chart_pts + context_pts - penalty))
    if setup["status"] == "none":
        total = min(total, NO_SETUP_CAP)  # without a chart setup there is no entry to be confident in

    reasons = []
    for f in factors:
        if f.risk:
            reasons.append({"effect": "risk", "label": f.label, "detail": f.detail, "points": None, "sources": f.sources[:3]})
        elif f.weight and abs(f.score) >= 0.15:
            reasons.append({"effect": "supports" if f.score * sign > 0 else "against", "label": f.label, "detail": f.detail,
                            "points": None, "sources": f.sources[:3]})
    reasons.sort(key=lambda r: {"risk": 0, "against": 1, "supports": 2}[r["effect"]])

    side = setup["direction"]
    if setup["status"] == "none":
        verdict = f"No {side} setup on the chart yet, so context alone cannot justify an entry."
    elif aligned > 0.15:
        verdict = f"News and macro back the {side}."
    elif aligned < -0.15:
        verdict = f"News and macro lean against the {side}: the chart may be early or wrong."
    else:
        verdict = f"News and macro are mixed for the {side}; it rests on the chart."
    if not any(f.weight > 0 and not f.risk for f in factors):
        verdict += " (No news or macro source could be reached, so the context part is a neutral placeholder.)"
    if risk >= 0.6:
        verdict += " A scheduled event is close: consider waiting for it, or trading smaller."

    return {
        "direction": side,
        "status": setup["status"],
        "confidence": round(total),
        "grade": grade(total),
        "chart_points": round(chart_pts, 1),
        "context_points": round(context_pts, 1),
        "event_penalty": round(penalty, 1),
        "verdict": verdict,
        "reasons": reasons,
    }
