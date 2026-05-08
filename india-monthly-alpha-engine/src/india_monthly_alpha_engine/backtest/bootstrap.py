"""Block bootstrap for monthly returns.

Per backtest_validity_methodology.md sections 5 and 6: block length 12
months (annual seasonality / autocorrelation), 10,000 resamples, 95%
confidence interval. The lower CI bound is what promotion gates check.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class BootstrapCI:
    point_estimate: float
    lower: float
    upper: float
    block_length: int
    resamples: int


def block_bootstrap_mean(
    monthly_returns: list[float],
    *,
    block_length: int = 12,
    resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapCI:
    """Block bootstrap CI on the mean.

    Resampling draws `ceil(N / block_length)` blocks of length `block_length`
    with replacement, concatenates, and trims to N. Per backtest_validity
    section 5, the canonical seed is fixed in the strategy_versions row.
    """
    n = len(monthly_returns)
    if n == 0:
        return BootstrapCI(0.0, 0.0, 0.0, block_length, resamples)

    point = sum(monthly_returns) / n

    blocks_per_sample = max(1, (n + block_length - 1) // block_length)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        sample: list[float] = []
        for _ in range(blocks_per_sample):
            start = rng.randrange(0, n)
            end = min(start + block_length, n)
            sample.extend(monthly_returns[start:end])
            if end == n and len(sample) < n:
                # wrap to keep block length when near the end
                wrap_remaining = block_length - (end - start)
                sample.extend(monthly_returns[:wrap_remaining])
        sample = sample[:n]
        means.append(sum(sample) / n)

    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = means[int(alpha * resamples)]
    hi = means[int((1.0 - alpha) * resamples) - 1]
    return BootstrapCI(point, lo, hi, block_length, resamples)
