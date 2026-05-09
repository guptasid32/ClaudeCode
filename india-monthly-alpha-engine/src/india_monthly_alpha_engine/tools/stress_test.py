"""Diverse-input stress test: many random (as_of_date, stock_subset) runs.

Picks `--runs` random (as_of_date, sampled_universe) pairs within
the allowed train+validation window and runs the orchestrator on
each. Reports per-run summaries plus aggregate stats. This is a soak
test for the engineering — it explores the input space to surface
crashes, NaNs, PIT inconsistencies, and performance regressions. It
is NOT a strategy backtest.

The script REFUSES to run on the locked holdout window
(2023-01-01 to 2024-12-31) per backtest_validity_methodology.md
section 7.5. The only way to test on holdout is the single-shot
promotion procedure.

Usage:

    python -m india_monthly_alpha_engine.tools.stress_test \
        --start 2014-01-01 --end 2022-12-31 \
        --runs 50 --universe-size 30 --seed 42
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import date, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import get_settings
from ..app.logging_config import configure_logging, get_logger
from ..db.models_raw import Company, IndexConstituentHistory
from ..db.session import get_session
from ..engines.orchestrator import run_monthly_cycle

HOLDOUT_START = date(2023, 1, 1)
HOLDOUT_END = date(2024, 12, 31)


class StressOutcome(NamedTuple):
    as_of: date
    universe_size: int
    pes: int
    index_amount: int
    active_amount: int
    n_strong: int
    elapsed_seconds: float


def _random_business_date(start: date, end: date, rng: random.Random) -> date:
    span_days = (end - start).days
    while True:
        d = start + timedelta(days=rng.randrange(0, max(1, span_days)))
        if d.weekday() < 5:
            return d


def _sample_universe(
    session: Session, as_of: date, sample_size: int, rng: random.Random, *, index_name: str
) -> list[int]:
    stmt = select(IndexConstituentHistory.company_id).where(
        IndexConstituentHistory.index_name == index_name,
        IndexConstituentHistory.effective_from <= as_of,
    )
    pool = list(session.execute(stmt).scalars().all())
    if not pool:
        # fallback to companies table
        pool = list(session.execute(select(Company.id)).scalars().all())
    if len(pool) <= sample_size:
        return pool
    return rng.sample(pool, sample_size)


def _filter_to_subset(session: Session, as_of: date, allowed: set[int], index_name: str) -> None:
    """Mark constituents not in `allowed` as not-effective on `as_of` for this run.

    Phase 12 orchestrator intersects universe with index constituents at
    as_of_date. To stress-test against a specific subset, we temporarily
    write a private index named NIFTY_500_STRESS for this run only and
    point the orchestrator at it.
    """
    # Clear any previous stress index for this date
    session.execute(
        IndexConstituentHistory.__table__.delete().where(
            IndexConstituentHistory.index_name == "NIFTY_500_STRESS"
        )
    )
    for cid in allowed:
        session.add(
            IndexConstituentHistory(
                index_name="NIFTY_500_STRESS",
                company_id=cid,
                symbol=f"id_{cid}",
                effective_from=date(1990, 1, 1),
                effective_to=None,
                weight=1.0 / max(1, len(allowed)),
                source_id=session.execute(
                    select(IndexConstituentHistory.source_id)
                    .where(IndexConstituentHistory.company_id == cid)
                    .limit(1)
                ).scalar()
                or 1,
            )
        )
    session.flush()


def run_stress_test(
    *,
    start: date,
    end: date,
    runs: int,
    universe_size: int,
    seed: int,
    cohort_step_days: int = 365,
    benchmark_index: str = "NIFTY_500_TRI",
) -> list[StressOutcome]:
    if start >= HOLDOUT_START and end > HOLDOUT_START:
        raise SystemExit(
            f"refusing to run stress test inside the locked holdout window "
            f"({HOLDOUT_START}..{HOLDOUT_END}); see backtest_validity_methodology.md section 7.5"
        )
    if end >= HOLDOUT_START:
        end = HOLDOUT_START - timedelta(days=1)

    settings = get_settings()
    configure_logging(settings)
    log = get_logger("stress")
    rng = random.Random(seed)

    outcomes: list[StressOutcome] = []
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with get_session(settings.sqlite_url) as session:
        for run_idx in range(runs):
            as_of = _random_business_date(start, end, rng)
            sample = _sample_universe(
                session, as_of, universe_size, rng, index_name="NIFTY_500"
            )
            _filter_to_subset(session, as_of, set(sample), index_name="NIFTY_500")
            t0 = time.perf_counter()
            try:
                result = run_monthly_cycle(
                    session,
                    as_of_date=as_of,
                    benchmark_index=benchmark_index,
                    universe_index="NIFTY_500_STRESS",
                    cohort_observation_step_days=cohort_step_days,
                )
            except Exception as exc:  # noqa: BLE001  surfacing for stress
                log.error("stress.run_failed", run=run_idx, as_of=str(as_of), error=str(exc))
                continue
            elapsed = time.perf_counter() - t0
            outcomes.append(
                StressOutcome(
                    as_of=as_of,
                    universe_size=len(sample),
                    pes=result.pes,
                    index_amount=result.index_amount,
                    active_amount=result.active_amount,
                    n_strong=result.n_strong_candidates,
                    elapsed_seconds=elapsed,
                )
            )
            log.info(
                "stress.run_ok",
                run=run_idx,
                as_of=str(as_of),
                universe=len(sample),
                pes=result.pes,
                strong=result.n_strong_candidates,
                index=result.index_amount,
                active=result.active_amount,
                seconds=round(elapsed, 2),
            )

        # Clean up the stress index
        session.execute(
            IndexConstituentHistory.__table__.delete().where(
                IndexConstituentHistory.index_name == "NIFTY_500_STRESS"
            )
        )

        # Roll back persisted predictions/plans for these stress runs?  We
        # intentionally KEEP them: the audit trail is more valuable than the
        # noise. Filter them out by replay_date if you want to exclude.

    return outcomes


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, default=date(2014, 1, 1))
    p.add_argument("--end", type=date.fromisoformat, default=date(2022, 12, 31))
    p.add_argument("--runs", type=int, default=50)
    p.add_argument("--universe-size", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--cohort-step-days", type=int, default=365)
    args = p.parse_args()

    outcomes = run_stress_test(
        start=args.start,
        end=args.end,
        runs=args.runs,
        universe_size=args.universe_size,
        seed=args.seed,
        cohort_step_days=args.cohort_step_days,
    )

    if not outcomes:
        print("no successful runs", file=sys.stderr)
        return 1

    pes_list = [o.pes for o in outcomes]
    avg_pes = sum(pes_list) / len(pes_list)
    avg_index_pct = sum(o.index_amount for o in outcomes) / (25_000 * len(outcomes))
    print(f"runs_attempted={args.runs} runs_completed={len(outcomes)}")
    print(f"avg_pes={avg_pes:.1f}  min_pes={min(pes_list)}  max_pes={max(pes_list)}")
    print(f"avg_index_share={avg_index_pct:.1%}")
    print(f"avg_seconds_per_run={sum(o.elapsed_seconds for o in outcomes)/len(outcomes):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
