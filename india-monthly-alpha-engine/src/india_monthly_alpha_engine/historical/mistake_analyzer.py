"""Phase 16: mistake analyzer.

Reads `historical_predictions` joined with `historical_outcomes` (when
available) and surfaces per-strategy patterns: false positives, missed
opportunities, sector concentration of mistakes. The mistake analyzer
runs only on the train + validation window per backtest_validity
methodology.md section 7.4 — never on the holdout.

This v1 module operates on dataclasses passed in by the caller; the
DB join layer is added when historical_predictions / historical_outcomes
ORM models arrive (Phase 16+).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class HistoricalCase:
    company_id: int
    symbol: str
    sector: str | None
    strategy_version_id: int
    monthly_buy_score: int
    classification: str  # "candidate" | "reject"
    forward_return_12m: float | None
    benchmark_return_12m: float | None


@dataclass(frozen=True)
class MistakeReport:
    n_evaluated: int
    n_pending: int
    false_positives: int  # bought, underperformed > 5pp
    missed_opportunities: int  # rejected, outperformed > 5pp
    avg_excess_return_buys: float
    avg_excess_return_rejects: float
    by_sector_excess_return: dict[str, float]


def analyze(cases: list[HistoricalCase]) -> MistakeReport:
    evaluated = [c for c in cases if c.forward_return_12m is not None and c.benchmark_return_12m is not None]
    pending = len(cases) - len(evaluated)
    if not evaluated:
        return MistakeReport(
            n_evaluated=0,
            n_pending=pending,
            false_positives=0,
            missed_opportunities=0,
            avg_excess_return_buys=0.0,
            avg_excess_return_rejects=0.0,
            by_sector_excess_return={},
        )

    fp = 0
    missed = 0
    buys_excess: list[float] = []
    rejects_excess: list[float] = []
    by_sector: dict[str, list[float]] = defaultdict(list)

    for c in evaluated:
        excess = c.forward_return_12m - c.benchmark_return_12m  # type: ignore[operator]
        if c.sector:
            by_sector[c.sector].append(excess)
        if c.classification == "candidate":
            buys_excess.append(excess)
            if excess < -0.05:
                fp += 1
        else:
            rejects_excess.append(excess)
            if excess > 0.05:
                missed += 1

    return MistakeReport(
        n_evaluated=len(evaluated),
        n_pending=pending,
        false_positives=fp,
        missed_opportunities=missed,
        avg_excess_return_buys=statistics.fmean(buys_excess) if buys_excess else 0.0,
        avg_excess_return_rejects=statistics.fmean(rejects_excess) if rejects_excess else 0.0,
        by_sector_excess_return={s: statistics.fmean(v) for s, v in by_sector.items()},
    )
