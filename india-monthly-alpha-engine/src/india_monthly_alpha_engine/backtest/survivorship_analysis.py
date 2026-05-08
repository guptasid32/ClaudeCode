"""Phase 14 survivorship analysis (backtest_validity_methodology.md section 10.2).

The survivor-only and survivorship-correct universes both come out of
pit/universe.py. Backtests run on each and compare CAGR; the gap is
the survivorship bias estimate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurvivorshipGap:
    survivor_only_cagr: float
    survivorship_correct_cagr: float
    gap_pp: float  # percentage points; positive = survivor-only outperforms

    @property
    def coverage_warning(self) -> str | None:
        """If the gap is unrealistically small, the seed list is probably incomplete.
        Per validity 10.2, < 1pp on a non-trivial backtest blocks promotion until the
        delisted-companies seed list grows."""
        if abs(self.gap_pp) < 1.0:
            return (
                "survivorship gap < 1pp annualised — delisted-company seed list "
                "is probably incomplete; expand to >= 50 confirmed cases per "
                "data_sources.md section 6 before promotion"
            )
        return None


def compute_survivorship_gap(
    survivor_only_cagr: float, survivorship_correct_cagr: float
) -> SurvivorshipGap:
    return SurvivorshipGap(
        survivor_only_cagr=survivor_only_cagr,
        survivorship_correct_cagr=survivorship_correct_cagr,
        gap_pp=(survivor_only_cagr - survivorship_correct_cagr) * 100.0,
    )
