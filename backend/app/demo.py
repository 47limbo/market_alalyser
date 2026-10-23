"""Deterministic synthetic candles for offline use and tests (`--demo` mode)."""

import random
import time

from .models import INTERVAL_MS, Candle


def demo_candles(interval: str = "15m", count: int = 500, seed: int = 7, start_price: float = 80_000.0) -> list[Candle]:
    """A random walk with regime changes and occasional impulsive moves, so every detector has something to find."""
    rng = random.Random(seed)
    step = INTERVAL_MS[interval]
    now = int(time.time() * 1000)
    t = (now // step) * step - count * step
    price = start_price
    drift = 0.0
    vol = start_price * 0.0015
    out: list[Candle] = []
    for i in range(count):
        if i % 60 == 0:
            drift = rng.uniform(-0.6, 0.6) * vol
        shock = rng.gauss(0, vol)
        if rng.random() < 0.04:
            shock += rng.choice([-1, 1]) * vol * rng.uniform(2.5, 4.0)
        o = price
        c = max(1.0, o + drift + shock)
        h = max(o, c) + abs(rng.gauss(0, vol * 0.5))
        l = min(o, c) - abs(rng.gauss(0, vol * 0.5))
        v = abs(rng.gauss(100, 30)) * (1 + abs(shock) / vol)
        out.append(Candle(t, round(o, 2), round(h, 2), round(l, 2), round(c, 2), round(v, 3)))
        price = c
        t += step
    return out
