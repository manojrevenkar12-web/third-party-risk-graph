"""Intervals for rates."""

from __future__ import annotations

import math

Z = {0.9: 1.6449, 0.95: 1.96, 0.99: 2.5758}


def wilson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    z = Z[conf]
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)
