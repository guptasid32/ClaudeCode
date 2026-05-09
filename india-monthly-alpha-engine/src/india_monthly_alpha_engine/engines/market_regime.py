"""Phase 11 supplement: market regime classifier.

Per scoring_methodology.md section 3.1 and benchmark_methodology.md, the
regime is a categorical label in {bull, neutral, bear} computed from the
benchmark price series. The classifier consumes a list of benchmark
closing prices ending at as_of_date and returns the regime string.

v1 rules (kept simple deliberately; a champion-challenger experiment is
where richer regime models live):
- bull   : last close >= 200-day SMA AND breadth_proxy >= 0.60 AND vol_pct < 0.70
- bear   : last close <  200-day SMA AND breadth_proxy <  0.40
- neutral: otherwise

`breadth_proxy` is supplied by the caller (e.g., percentage of Nifty 500
constituents above their own 200-DMA on the as_of_date). When breadth is
not available, the classifier degrades gracefully to a 200-DMA-only rule.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    last_close: float
    sma_200: float
    breadth_proxy: float | None
    vol_percentile_12m: float | None
    rationale: str


def _vol_percentile(monthly_returns: list[float]) -> float | None:
    """Return the percentile rank (0..1) of the most recent 12-month
    volatility within a longer history of trailing-12-month volatilities.
    Requires at least 24 months of monthly returns."""
    if len(monthly_returns) < 24:
        return None
    rolling_vols: list[float] = []
    for i in range(12, len(monthly_returns) + 1):
        window = monthly_returns[i - 12 : i]
        rolling_vols.append(statistics.pstdev(window))
    if not rolling_vols:
        return None
    current = rolling_vols[-1]
    rank = sum(1 for v in rolling_vols if v <= current)
    return rank / len(rolling_vols)


def classify_regime(
    closes: list[float],
    *,
    breadth_proxy: float | None = None,
    monthly_returns: list[float] | None = None,
) -> RegimeResult:
    """Classify the market regime as of the last close.

    `closes` is the daily closing series ending on the as-of date.
    `breadth_proxy` is optional (0..1).
    `monthly_returns` is optional; needed for the volatility-percentile gate.
    """
    if len(closes) < 200:
        return RegimeResult(
            regime="neutral",
            last_close=closes[-1] if closes else 0.0,
            sma_200=0.0,
            breadth_proxy=breadth_proxy,
            vol_percentile_12m=None,
            rationale="insufficient history (<200 trading days) -> neutral",
        )

    last = closes[-1]
    sma200 = sum(closes[-200:]) / 200.0
    above_sma = last >= sma200
    vol_pct = _vol_percentile(monthly_returns) if monthly_returns else None

    if above_sma and (breadth_proxy is None or breadth_proxy >= 0.60) and (
        vol_pct is None or vol_pct < 0.70
    ):
        return RegimeResult(
            regime="bull",
            last_close=last,
            sma_200=sma200,
            breadth_proxy=breadth_proxy,
            vol_percentile_12m=vol_pct,
            rationale="above 200-DMA and breadth/vol gates passed",
        )
    if (not above_sma) and (breadth_proxy is None or breadth_proxy < 0.40):
        return RegimeResult(
            regime="bear",
            last_close=last,
            sma_200=sma200,
            breadth_proxy=breadth_proxy,
            vol_percentile_12m=vol_pct,
            rationale="below 200-DMA and breadth low",
        )
    return RegimeResult(
        regime="neutral",
        last_close=last,
        sma_200=sma200,
        breadth_proxy=breadth_proxy,
        vol_percentile_12m=vol_pct,
        rationale="mixed signals -> neutral",
    )
