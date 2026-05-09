"""Diversity-driven scenario selector for the adversarial loop.

Builds a multi-dimensional grid of scenario "cells" (time period x regime
proxy x sector concentration x liquidity profile x universe size x
survivorship-stress) and picks under-covered cells with probability
inversely proportional to coverage. Cells that have surfaced engineering
failures get an intensification weight so the loop keeps probing near
known-fragile inputs (the "GAN-like" hardness signal — but for finding
bugs, not tuning strategy parameters).

This is engineering robustness fuzzing, not strategy validation.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ScenarioCell:
    period: str  # e.g., "2014_2016"
    regime_proxy: str  # "rising" | "falling" | "choppy"
    sector_concentration: str  # "diversified" | "tilted" | "concentrated"
    liquidity_profile: str  # "high_only" | "mixed" | "with_illiquid"
    universe_size: str  # "small" | "medium" | "large"
    survivorship_stress: bool


@dataclass
class DiversityState:
    coverage: dict[ScenarioCell, int] = field(default_factory=lambda: defaultdict(int))
    failures: dict[ScenarioCell, int] = field(default_factory=lambda: defaultdict(int))
    total_runs: int = 0


PERIODS = ("2014_2016", "2016_2018", "2018_2020", "2020_2022", "2022_2023")
REGIMES = ("rising", "falling", "choppy")
SECTOR_CONC = ("diversified", "tilted", "concentrated")
LIQUIDITIES = ("high_only", "mixed", "with_illiquid")
SIZES = ("small", "medium", "large")
SURVIVORSHIP = (True, False)


def all_cells() -> Iterable[ScenarioCell]:
    for p in PERIODS:
        for r in REGIMES:
            for s in SECTOR_CONC:
                for liq in LIQUIDITIES:
                    for sz in SIZES:
                        for surv in SURVIVORSHIP:
                            yield ScenarioCell(p, r, s, liq, sz, surv)


def _cell_weight(state: DiversityState, cell: ScenarioCell) -> float:
    """Higher weight for under-covered cells; bonus for cells that have
    historically caused failures (intensify the hardness)."""
    base = 1.0 / (1.0 + state.coverage[cell])
    failure_bonus = 1.0 + 2.0 * state.failures[cell]
    return base * failure_bonus


def pick_cell(state: DiversityState, rng: random.Random) -> ScenarioCell:
    cells = list(all_cells())
    weights = [_cell_weight(state, c) for c in cells]
    return rng.choices(cells, weights=weights, k=1)[0]


def period_to_dates(period: str) -> tuple[date, date]:
    s, e = period.split("_")
    return date(int(s), 1, 1), date(int(e), 12, 31)


def universe_size_count(size: str) -> int:
    return {"small": 8, "medium": 25, "large": 60}[size]


@dataclass(frozen=True)
class SampledScenario:
    cell: ScenarioCell
    as_of_date: date
    universe_size_n: int


def sample_scenario(
    state: DiversityState, rng: random.Random
) -> SampledScenario:
    cell = pick_cell(state, rng)
    s, e = period_to_dates(cell.period)
    span = (e - s).days
    while True:
        d = s + __dt_timedelta(rng.randrange(0, max(1, span)))
        if d.weekday() < 5:
            break
    return SampledScenario(cell=cell, as_of_date=d, universe_size_n=universe_size_count(cell.universe_size))


def record_run(
    state: DiversityState, cell: ScenarioCell, *, failure: bool
) -> None:
    state.coverage[cell] += 1
    if failure:
        state.failures[cell] += 1
    state.total_runs += 1


def coverage_summary(state: DiversityState) -> dict[str, object]:
    cells = list(all_cells())
    covered = sum(1 for c in cells if state.coverage[c] > 0)
    failed_cells = sum(1 for c in cells if state.failures[c] > 0)
    return {
        "total_cells": len(cells),
        "covered_cells": covered,
        "coverage_pct": covered / len(cells),
        "cells_with_failures": failed_cells,
        "total_runs": state.total_runs,
        "total_failures": sum(state.failures.values()),
    }


def __dt_timedelta(days: int):  # tiny helper to avoid top-level datetime import noise
    from datetime import timedelta as _td
    return _td(days=days)
