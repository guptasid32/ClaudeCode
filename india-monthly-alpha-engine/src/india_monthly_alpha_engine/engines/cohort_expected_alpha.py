"""Phase 10: Cohort Expected Alpha engine.

Per scoring_methodology.md section 3:
- Cohort matching uses ONLY structural buckets (market_cap, sector,
  regime, liquidity) to avoid factor double-counting (review section 4.2).
- Lookback window: 10 years prior, ending 12 months before as_of_date.
- Cohort size rules: >=30 -> full confidence; 10-29 -> cap CEA at 60;
  <10 -> CEA=0 with E_Q penalty (-30 in evidence_quality_score).
- CEA_score = clip(50 + 250 * median_12m_excess_return, 0, 100).

The engine itself is a pure function over a list of cohort observations.
A separate builder is responsible for constructing the cohort observation
list from PIT data; the builder can be incrementally improved without
changing the score formula.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class CohortObservation:
    """One historical (company, observation_date) pair in a candidate's cohort.

    forward_excess_return_12m is the 12-month forward total return of the
    company starting from observation_date minus the benchmark's
    12-month return over the same window. For delisted companies the
    forward return must reflect realised proceeds (recovery_rate from
    DelistingEvent).
    """

    company_id: int
    observation_date: object  # date — kept as object to avoid import noise here
    forward_excess_return_12m: float


@dataclass(frozen=True)
class CohortStats:
    cohort_size: int
    median_excess_return: float
    mean_excess_return: float
    hit_rate: float
    p25_excess_return: float
    cea_score: int


def compute_cohort_stats(observations: list[CohortObservation]) -> CohortStats:
    """Compute cohort statistics and the CEA score per scoring_methodology.md
    section 3.4."""
    n = len(observations)
    if n == 0:
        return CohortStats(0, 0.0, 0.0, 0.0, 0.0, 0)

    excess_returns = sorted(o.forward_excess_return_12m for o in observations)
    median = statistics.median(excess_returns)
    mean = statistics.fmean(excess_returns)
    hit_rate = sum(1 for r in excess_returns if r > 0) / n
    # 25th percentile via linear interpolation matching numpy default
    if n == 1:
        p25 = excess_returns[0]
    else:
        idx = 0.25 * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        p25 = excess_returns[lo] * (1 - frac) + excess_returns[hi] * frac

    cea_raw = 50.0 + 250.0 * median
    cea_clipped = int(round(max(0.0, min(100.0, cea_raw))))

    if n < 10:
        cea_score = 0
    elif n < 30:
        cea_score = min(cea_clipped, 60)
    else:
        cea_score = cea_clipped

    return CohortStats(
        cohort_size=n,
        median_excess_return=median,
        mean_excess_return=mean,
        hit_rate=hit_rate,
        p25_excess_return=p25,
        cea_score=cea_score,
    )
