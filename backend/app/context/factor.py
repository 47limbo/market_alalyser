from dataclasses import asdict, dataclass, field


@dataclass
class Factor:
    """One piece of evidence for or against the asset.

    score runs from -1 (bearish) to +1 (bullish). Event risks score 0 and set risk instead: they say
    "price may jump either way", which lowers confidence in any entry rather than favouring a side.
    """

    key: str
    group: str  # "Rates and yields", "Fed", "Earnings", "News", "Macro and politics", "Deep research"
    label: str
    detail: str
    score: float = 0.0
    weight: float = 1.0
    risk: float = 0.0  # 0 to 1: how much this event should lower confidence in a new entry
    sources: list[dict] = field(default_factory=list)  # {"title", "url"}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signal"] = "risk" if self.risk else "bullish" if self.score > 0.15 else "bearish" if self.score < -0.15 else "neutral"
        return d


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
