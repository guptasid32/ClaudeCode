"""Phase 12 orchestrator integration tests on synthetic data.

These tests exercise run_monthly_cycle end-to-end against a synthetic
universe (companies, prices, financials, corp actions, index
constituents, benchmark prices). They are deliberately diverse — each
scenario stresses a different decision branch.

These are integration tests, not validity tests. They verify the
engines compose correctly on internally-consistent data; they do NOT
validate the strategy beats a real-world benchmark (no real-world data
exists in this sandbox).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from india_monthly_alpha_engine.db.models import (
    HistoricalPrediction,
    MonthlyBuyAction,
    MonthlyDeploymentPlan,
)
from india_monthly_alpha_engine.engines.market_regime import classify_regime
from india_monthly_alpha_engine.engines.orchestrator import run_monthly_cycle

from .synthetic import CompanySpec, seed_universe, standard_specs

AS_OF = date(2024, 6, 28)
HISTORY_START = date(2014, 1, 1)


@pytest.fixture
def synthetic_session(session: Session) -> Session:
    seed_universe(
        session,
        specs=standard_specs(as_of=AS_OF, count=12),
        history_start=HISTORY_START,
        as_of_date=AS_OF,
    )
    return session


def test_orchestrator_runs_end_to_end(synthetic_session: Session) -> None:
    result = run_monthly_cycle(
        synthetic_session,
        as_of_date=AS_OF,
        cohort_observation_step_days=365,  # one observation per year is enough for the test
    )
    assert result.plan_id > 0
    assert result.n_candidates_evaluated == 12
    assert 0 <= result.pes <= 100
    assert result.index_amount + result.active_amount == 25_000


def test_orchestrator_persists_plan_and_actions(synthetic_session: Session) -> None:
    result = run_monthly_cycle(
        synthetic_session, as_of_date=AS_OF, cohort_observation_step_days=120
    )
    plan = synthetic_session.get(MonthlyDeploymentPlan, result.plan_id)
    assert plan is not None
    assert plan.rebalance_date == AS_OF
    assert plan.benchmark == "NIFTY_500_TRI"

    actions = (
        synthetic_session.execute(
            select(MonthlyBuyAction).where(MonthlyBuyAction.deployment_plan_id == plan.id)
        )
        .scalars()
        .all()
    )
    assert len(actions) == result.n_actions


def test_orchestrator_writes_historical_predictions_with_hashes(synthetic_session: Session) -> None:
    run_monthly_cycle(synthetic_session, as_of_date=AS_OF, cohort_observation_step_days=120)
    predictions = (
        synthetic_session.execute(select(HistoricalPrediction).where(HistoricalPrediction.replay_date == AS_OF))
        .scalars()
        .all()
    )
    # one prediction per evaluated candidate
    assert len(predictions) == 12
    hashes = {p.feature_snapshot_hash for p in predictions}
    # each candidate's snapshot is distinct -> distinct hashes
    assert len(hashes) == 12
    # hashes are 64-hex
    assert all(len(h) == 64 for h in hashes)


def test_orchestrator_replay_determinism(synthetic_session: Session) -> None:
    """Running the same cycle twice produces identical hashes (point_in_time
    methodology section 7 / backtest_validity 10.5)."""
    a = run_monthly_cycle(synthetic_session, as_of_date=AS_OF, cohort_observation_step_days=120)
    # Clear the previous run to avoid uniqueness collisions in unique-on-(replay_date, company_id)
    # tables; for v1 simplicity we re-query and assert the FIRST run's hashes are stable across
    # a fresh cycle on a separate session with the same seed.
    # Build a parallel synthetic db on a fresh in-memory engine
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from india_monthly_alpha_engine.db import Base, models, models_raw  # noqa: F401

    from .synthetic import seed_universe as _seed
    from .synthetic import standard_specs as _specs

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(engine)  # noqa: N806  factory class, capital is conventional
    with SessionFactory() as fresh:
        _seed(fresh, specs=_specs(as_of=AS_OF, count=12), history_start=HISTORY_START, as_of_date=AS_OF)
        fresh.commit()
        b = run_monthly_cycle(fresh, as_of_date=AS_OF, cohort_observation_step_days=120)

    # Same PES, same actions count
    assert a.pes == b.pes
    assert a.n_actions == b.n_actions

    hashes_a = sorted(
        h for (h,) in synthetic_session.execute(
            select(HistoricalPrediction.feature_snapshot_hash).where(HistoricalPrediction.replay_date == AS_OF)
        ).all()
    )
    with SessionFactory() as s2:
        # re-read from fresh DB
        hashes_b = sorted(
            h for (h,) in s2.execute(
                select(HistoricalPrediction.feature_snapshot_hash).where(HistoricalPrediction.replay_date == AS_OF)
            ).all()
        )
    # The hashes themselves come from feature snapshots that depend on the random
    # walk; on the same seed and same code, they should match across runs.
    assert hashes_a == hashes_b


def test_pes_lower_when_universe_low_quality(session: Session) -> None:
    """If every candidate is low-quality, PES should be modest and most rupees go to index."""
    listing = date(AS_OF.year - 12, 1, 1)
    weak_specs = [
        CompanySpec(
            symbol=f"WEAK{i:02d}",
            company_name=f"Weak {i}",
            sector="industrials",
            market_cap_category="small",
            listing_date=listing,
            initial_price=100.0 + i * 10,
            monthly_drift=-0.002,  # slightly negative drift
            monthly_vol=0.10,
            quarterly_revenue=500.0 * (i + 1),
            quarterly_revenue_growth=-0.03,  # declining
            quarterly_pat_margin=0.02,
            ocf_to_pat=0.3,  # poor cash conversion
            debt_to_equity=1.5,  # heavy leverage
        )
        for i in range(8)
    ]
    seed_universe(session, specs=weak_specs, history_start=HISTORY_START, as_of_date=AS_OF, seed=11)
    result = run_monthly_cycle(session, as_of_date=AS_OF, cohort_observation_step_days=120)
    # With weak fundamentals across the board, almost everything should go to the index
    assert result.index_amount >= 20_000


def test_orchestrator_intersects_universe_with_index_constituents(synthetic_session: Session) -> None:
    """Companies not in the configured universe_index are excluded from candidates."""
    # NIFTY_50 is not seeded -> intersection is empty -> no candidates
    result = run_monthly_cycle(
        synthetic_session,
        as_of_date=AS_OF,
        universe_index="NIFTY_50",
        cohort_observation_step_days=365,
    )
    assert result.n_candidates_evaluated == 0
    # All capital should go to index (no candidates implies PES <= 50)
    assert result.index_amount == 25_000


def test_market_regime_classifier_buckets_synthetic_series() -> None:
    """Different drift profiles should land in different regime buckets."""
    # Strongly rising series -> bull regime
    rising = [100.0 * (1.0 + 0.001) ** i for i in range(300)]
    bull = classify_regime(rising, breadth_proxy=0.7)
    assert bull.regime == "bull"

    # Strongly falling series -> bear regime
    falling = [200.0 * (1.0 - 0.001) ** i for i in range(300)]
    bear = classify_regime(falling, breadth_proxy=0.3)
    assert bear.regime == "bear"

    # Flat series -> neutral
    flat = [100.0] * 300
    neutral = classify_regime(flat, breadth_proxy=0.5)
    assert neutral.regime in {"neutral", "bull"}  # right at threshold; not bear


def test_market_regime_insufficient_history_returns_neutral() -> None:
    sparse = [100.0] * 50
    result = classify_regime(sparse)
    assert result.regime == "neutral"


def test_orchestrator_handles_empty_db(session: Session) -> None:
    """No data ingested at all -> orchestrator runs cleanly with all-index allocation."""
    result = run_monthly_cycle(session, as_of_date=AS_OF, cohort_observation_step_days=120)
    assert result.n_candidates_evaluated == 0
    assert result.index_amount == 25_000
    assert result.active_amount == 0


def test_orchestrator_distinct_hashes_per_candidate(synthetic_session: Session) -> None:
    """Each candidate's feature_snapshot_hash must be unique even when sub-scores
    happen to land on similar values."""
    run_monthly_cycle(synthetic_session, as_of_date=AS_OF, cohort_observation_step_days=120)
    rows = synthetic_session.execute(
        select(HistoricalPrediction.company_id, HistoricalPrediction.feature_snapshot_hash).where(
            HistoricalPrediction.replay_date == AS_OF
        )
    ).all()
    hashes = [h for _, h in rows]
    assert len(hashes) == len(set(hashes))
