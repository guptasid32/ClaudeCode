"""Phase 10 cohort builder: turns PIT history into CohortObservations.

Per scoring_methodology.md section 3:
- Lookback window: as_of_date - 10y to as_of_date - 12m (window ends 12m
  before as_of so each observation has a complete 12m forward return).
- Match dimensions (structural buckets only, to avoid factor double-
  counting): market_cap, sector, regime, liquidity.
- Universe: get_companies_active_at(t) UNION get_delisted_companies_active_at(t).
- Forward return: 12m total return from observation_date minus benchmark
  TRI return over the same window.

This module returns a list of CohortObservation suitable for
compute_cohort_stats(). It is deliberately constructed so a sparse
historical dataset returns a small cohort (and therefore CEA=0) rather
than crashing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..pit.point_in_time_loader import get_company_metadata, get_prices_until
from ..pit.universe import get_universe_at
from .cohort_expected_alpha import CohortObservation


@dataclass(frozen=True)
class CandidateBucket:
    market_cap_bucket: str  # "large" | "mid" | "small" | "micro"
    sector: str  # canonical sector name
    regime: str  # "bull" | "neutral" | "bear"
    liquidity_bucket: str  # "high" | "mid" | "low"


def _market_cap_bucket(category: str | None) -> str:
    """Map the companies.market_cap_category string to a v1 bucket."""
    if not category:
        return "small"
    cat = category.lower()
    if "large" in cat:
        return "large"
    if "mid" in cat:
        return "mid"
    if "small" in cat:
        return "small"
    if "micro" in cat:
        return "micro"
    return "small"


def _liquidity_bucket_from_prices(session: Session, company_id: int, as_of: date) -> str:
    """Approximate liquidity bucket from the trailing 30-day average turnover."""
    rows = get_prices_until(session, company_id, as_of)
    last_30 = rows[-30:]
    if not last_30:
        return "low"
    turnovers = [r.turnover for r in last_30 if r.turnover is not None]
    if not turnovers:
        return "low"
    adv_cr = (sum(turnovers) / len(turnovers)) / 1e7
    if adv_cr >= 50:
        return "high"
    if adv_cr >= 5:
        return "mid"
    return "low"


def candidate_bucket(session: Session, company_id: int, as_of: date, regime: str) -> CandidateBucket | None:
    meta = get_company_metadata(session, company_id)
    if meta is None:
        return None
    return CandidateBucket(
        market_cap_bucket=_market_cap_bucket(meta.market_cap_category),
        sector=meta.sector or "unknown",
        regime=regime,
        liquidity_bucket=_liquidity_bucket_from_prices(session, company_id, as_of),
    )


def _adjusted_close_at_or_before(rows, target: date) -> float | None:
    """Return the adjusted close at the latest trade_date <= target, or None."""
    last: float | None = None
    for r in rows:
        if r.trade_date > target:
            break
        last = r.adjusted_close if r.adjusted_close is not None else r.close
    return last


def _company_total_return(session: Session, company_id: int, start: date, end: date) -> float | None:
    rows = get_prices_until(session, company_id, end + timedelta(days=1))
    p_start = _adjusted_close_at_or_before(rows, start)
    p_end = _adjusted_close_at_or_before(rows, end)
    if p_start is None or p_end is None or p_start <= 0:
        return None
    return (p_end / p_start) - 1.0


def build_cohort(
    session: Session,
    *,
    candidate_id: int,
    as_of_date: date,
    regime_at: Callable[[date], str],
    benchmark_return: Callable[[date, date], float | None],
    lookback_years: int = 10,
    observation_step_days: int = 30,
) -> list[CohortObservation]:
    """Walk historical observation dates monthly and collect cohort matches.

    `regime_at(date)` returns the market regime classification on a past
    date. `benchmark_return(start, end)` returns the benchmark's total
    return between two dates (or None if unavailable). The two callables
    are injected so the builder is independent of any specific benchmark
    or regime implementation.
    """
    bucket = candidate_bucket(session, candidate_id, as_of_date, regime_at(as_of_date))
    if bucket is None:
        return []

    earliest_obs = date(as_of_date.year - lookback_years, as_of_date.month, 1)
    latest_obs = as_of_date - timedelta(days=365)
    if latest_obs <= earliest_obs:
        return []

    observations: list[CohortObservation] = []
    obs = earliest_obs
    while obs <= latest_obs:
        candidates = get_universe_at(session, obs)
        candidates.discard(candidate_id)
        for cid in candidates:
            cb = candidate_bucket(session, cid, obs, regime_at(obs))
            if cb is None or cb != bucket:
                continue
            forward_end = obs + timedelta(days=365)
            company_ret = _company_total_return(session, cid, obs, forward_end)
            if company_ret is None:
                continue
            bench_ret = benchmark_return(obs, forward_end)
            if bench_ret is None:
                continue
            observations.append(
                CohortObservation(
                    company_id=cid,
                    observation_date=obs,
                    forward_excess_return_12m=company_ret - bench_ret,
                )
            )
        obs = obs + timedelta(days=observation_step_days)

    return observations
