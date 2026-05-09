"""Adversarial diversity-driven engineering soak loop.

Runs the orchestrator over diverse, "hardest available" scenarios and
checks engineering invariants on every run. When it finds a failure, it
logs it (so the developer can fix the bug) and biases future scenario
selection toward similar inputs (intensification).

The loop stops when one of:
  - --max-runs total runs completed,
  - --converge-streak consecutive runs with zero invariant failures and
    average diversity coverage above --converge-coverage,
  - the user kills it.

Every N runs (--refresh-every) the data fetcher is invoked to pull
additional historical data so the testbed evolves, not stays static.

What this loop does NOT do:
  - It does not change strategy weights or thresholds. Strategy
    promotion goes through the train/validation/locked-holdout
    discipline in backtest_validity_methodology.md section 7.
  - It does not run on the locked holdout (2023-01-01..2024-12-31).

Usage:

    python -m india_monthly_alpha_engine.tools.adversarial_loop \
        --max-runs 500 --refresh-every 50 --seed 7
"""

from __future__ import annotations

import argparse
import random
import time
import traceback
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import get_settings
from ..app.logging_config import configure_logging, get_logger
from ..db.models import HistoricalPrediction
from ..db.models_raw import Company, IndexConstituentHistory
from ..db.session import get_session
from ..engines.orchestrator import run_monthly_cycle
from .diversity import (
    DiversityState,
    SampledScenario,
    coverage_summary,
    record_run,
    sample_scenario,
)

HOLDOUT_START = date(2023, 1, 1)


class InvariantError(Exception):
    """Raised when an engineering invariant is violated during a stress run."""


def _check_invariants(result, session: Session, scenario: SampledScenario, *, capital: int = 25_000) -> None:
    """The engineering invariants the loop verifies on every run.

    Failures are real bugs and should be fixed in code (not by tuning
    weights or thresholds away the symptom).
    """
    if result.index_amount + result.active_amount != capital:
        raise InvariantError(
            f"capital_split: {result.index_amount} + {result.active_amount} != {capital}"
        )
    if not 0 <= result.pes <= 100:
        raise InvariantError(f"pes_out_of_range: {result.pes}")
    if result.n_strong_candidates < 0 or result.n_strong_candidates > result.n_candidates_evaluated:
        raise InvariantError(
            f"strong_count: {result.n_strong_candidates} > total {result.n_candidates_evaluated}"
        )
    # PIT property spot-check: every prediction this run must have a 64-hex hash
    rows = session.execute(
        select(HistoricalPrediction.feature_snapshot_hash).where(
            HistoricalPrediction.replay_date == scenario.as_of_date
        )
    ).scalars().all()
    for h in rows:
        if not h or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise InvariantError(f"bad_hash: {h!r}")


def _select_subset(session: Session, sample_size: int, rng: random.Random) -> list[int]:
    pool = list(
        session.execute(select(Company.id).where(Company.exchange == "NSE")).scalars().all()
    )
    if len(pool) <= sample_size:
        return pool
    return rng.sample(pool, sample_size)


def _install_subset_index(session: Session, company_ids: list[int]) -> None:
    """Same trick as stress_test.py: temporarily install a private index
    name "ADVERSARIAL_SUBSET" so the orchestrator filters to this subset."""
    session.execute(
        IndexConstituentHistory.__table__.delete().where(
            IndexConstituentHistory.index_name == "ADVERSARIAL_SUBSET"
        )
    )
    fallback_src = session.execute(
        select(IndexConstituentHistory.source_id).limit(1)
    ).scalar() or 1
    for cid in company_ids:
        session.add(
            IndexConstituentHistory(
                index_name="ADVERSARIAL_SUBSET",
                company_id=cid,
                symbol=f"id_{cid}",
                effective_from=date(1990, 1, 1),
                effective_to=None,
                weight=1.0 / max(1, len(company_ids)),
                source_id=fallback_src,
            )
        )
    session.flush()


def _maybe_refresh_data(every: int, run_idx: int, log) -> None:
    if every <= 0 or run_idx == 0 or run_idx % every != 0:
        return
    try:
        from . import data_fetcher  # local import to avoid hard dep when not used

        ns = argparse.Namespace(
            random_symbols=5,
            refresh_count=10,
            extend_history_years=1,
            seed=run_idx,
        )
        data_fetcher.cmd_refresh(ns)
        log.info("loop.data_refreshed", run=run_idx)
    except Exception as e:
        log.warning("loop.data_refresh_failed", error=str(e))


def run_loop(
    *,
    max_runs: int,
    converge_streak: int,
    converge_coverage: float,
    refresh_every: int,
    seed: int,
    cohort_step_days: int,
    log_path: Path | None = None,
) -> dict[str, object]:
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("adversarial")
    rng = random.Random(seed)
    state = DiversityState()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
    else:
        log_handle = None

    consecutive_clean = 0
    total_failures = 0

    with get_session(settings.sqlite_url) as session:
        for run_idx in range(max_runs):
            scenario = sample_scenario(state, rng)
            if scenario.as_of_date >= HOLDOUT_START:
                # diversity selector knows about period buckets; double-guard anyway
                continue
            _maybe_refresh_data(refresh_every, run_idx, log)

            subset = _select_subset(session, scenario.universe_size_n, rng)
            _install_subset_index(session, subset)

            t0 = time.perf_counter()
            try:
                result = run_monthly_cycle(
                    session,
                    as_of_date=scenario.as_of_date,
                    universe_index="ADVERSARIAL_SUBSET",
                    cohort_observation_step_days=cohort_step_days,
                )
                _check_invariants(result, session, scenario)
                failure = False
                msg = "ok"
            except Exception as e:
                failure = True
                msg = f"{type(e).__name__}: {e}"
                tb = traceback.format_exc()
                log.error(
                    "loop.failure",
                    run=run_idx,
                    cell=str(scenario.cell),
                    as_of=str(scenario.as_of_date),
                    error=msg,
                )
                if log_handle:
                    log_handle.write(
                        f"\n--- run {run_idx} {scenario.cell} {scenario.as_of_date} ---\n{tb}\n"
                    )
                    log_handle.flush()
                total_failures += 1

            elapsed = time.perf_counter() - t0
            record_run(state, scenario.cell, failure=failure)

            log.info(
                "loop.run",
                run=run_idx,
                cell_period=scenario.cell.period,
                cell_regime=scenario.cell.regime_proxy,
                cell_size=scenario.cell.universe_size,
                as_of=str(scenario.as_of_date),
                universe=len(subset),
                status=msg,
                elapsed_s=round(elapsed, 2),
            )

            if failure:
                consecutive_clean = 0
            else:
                consecutive_clean += 1

            cov = coverage_summary(state)
            if (
                consecutive_clean >= converge_streak
                and cov["coverage_pct"] >= converge_coverage
            ):
                log.info(
                    "loop.converged",
                    runs=state.total_runs,
                    streak=consecutive_clean,
                    coverage=cov["coverage_pct"],
                )
                break

        # cleanup the private index
        session.execute(
            IndexConstituentHistory.__table__.delete().where(
                IndexConstituentHistory.index_name == "ADVERSARIAL_SUBSET"
            )
        )

    if log_handle:
        log_handle.close()

    return {
        "runs": state.total_runs,
        "failures": total_failures,
        **coverage_summary(state),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--max-runs", type=int, default=500)
    p.add_argument("--converge-streak", type=int, default=50, help="consecutive failure-free runs to declare converged")
    p.add_argument("--converge-coverage", type=float, default=0.6, help="min fraction of cells covered before convergence allowed")
    p.add_argument("--refresh-every", type=int, default=50, help="run data_fetcher refresh every N runs (0 to disable)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--cohort-step-days", type=int, default=365)
    p.add_argument("--failure-log", type=Path, default=Path("logs/adversarial_failures.log"))
    args = p.parse_args()

    summary = run_loop(
        max_runs=args.max_runs,
        converge_streak=args.converge_streak,
        converge_coverage=args.converge_coverage,
        refresh_every=args.refresh_every,
        seed=args.seed,
        cohort_step_days=args.cohort_step_days,
        log_path=args.failure_log,
    )

    print("=== adversarial loop summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0 if summary["failures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
