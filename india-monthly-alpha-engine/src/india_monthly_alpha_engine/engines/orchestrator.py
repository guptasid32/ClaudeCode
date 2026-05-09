"""Live monthly orchestrator: ties PIT + features + scores + deployment together.

`run_monthly_cycle(session, as_of_date, monthly_capital, ...)` is the
single entry point invoked by `imae monthly`. It composes the engines
in the order specified by scoring_methodology.md and persists the
deployment plan, per-action records, and historical_predictions for
later replay verification.

This implementation is functional but conservative: it operates on
whatever PIT data is in the database, and silently downgrades scores
where data is too sparse rather than crashing. Every prediction is
hashed via feature_snapshot_hash so a future replay can verify
reproducibility.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    BenchmarkPrice,
    HistoricalPrediction,
    MonthlyBuyAction,
    MonthlyDeploymentPlan,
    PortfolioHolding,
)
from ..features.scoring_features import (
    business_quality_score,
    earnings_acceleration_score,
    evidence_quality_score,
    governance_safety_score,
    liquidity_score,
    sector_tailwind_score,
    technical_confirmation_score,
    valuation_sanity_score,
)
from ..pit.point_in_time_loader import (
    feature_snapshot_hash,
    get_company_metadata,
    get_financials_available_until,
    get_index_constituents_as_of,
    get_prices_until,
)
from ..pit.universe import get_universe_at
from .cohort_builder import build_cohort
from .cohort_expected_alpha import compute_cohort_stats
from .deployment import (
    CandidateForDeployment,
    build_deployment_plan,
)
from .market_regime import classify_regime
from .monthly_buy import SubScores, monthly_buy_score
from .portfolio_edge import (
    CandidateRecord,
    HoldingRecord,
    PortfolioContext,
    compute_portfolio_edge_score,
)


@dataclass(frozen=True)
class CycleResult:
    plan_id: int
    rebalance_date: date
    pes: int
    index_amount: int
    active_amount: int
    n_candidates_evaluated: int
    n_strong_candidates: int
    n_actions: int


def _benchmark_close_on_or_before(session: Session, index_name: str, as_of: date) -> float | None:
    stmt = (
        select(BenchmarkPrice)
        .where(BenchmarkPrice.index_name == index_name, BenchmarkPrice.trade_date <= as_of)
        .order_by(BenchmarkPrice.trade_date.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return row.tri_close if row.tri_close is not None else row.close


def make_benchmark_return_fn(session: Session, index_name: str = "NIFTY_500_TRI") -> Callable[[date, date], float | None]:
    def _bench_ret(start: date, end: date) -> float | None:
        a = _benchmark_close_on_or_before(session, index_name, start)
        b = _benchmark_close_on_or_before(session, index_name, end)
        if a is None or b is None or a <= 0:
            return None
        return (b / a) - 1.0
    return _bench_ret


def make_regime_fn(session: Session, index_name: str = "NIFTY_500_TRI") -> Callable[[date], str]:
    def _regime(at: date) -> str:
        stmt = (
            select(BenchmarkPrice)
            .where(BenchmarkPrice.index_name == index_name, BenchmarkPrice.trade_date <= at)
            .order_by(BenchmarkPrice.trade_date.asc())
        )
        rows = session.execute(stmt).scalars().all()
        closes = [r.tri_close if r.tri_close is not None else r.close for r in rows]
        return classify_regime(closes).regime
    return _regime


def _compute_subscores(
    session: Session,
    company_id: int,
    as_of: date,
    cea_score: int,
) -> tuple[SubScores, int]:
    """Compute the nine sub-scores for a candidate. Returns (subs, mbs_evidence_quality)."""
    prices = get_prices_until(session, company_id, as_of)
    fins = get_financials_available_until(session, company_id, as_of)

    last_close = prices[-1].close if prices else 0.0

    bq = business_quality_score(fins)
    ea = earnings_acceleration_score(fins)
    vs = valuation_sanity_score(last_close, fins) if last_close > 0 else 50
    tc = technical_confirmation_score(prices, as_of) if prices else 50
    liq = liquidity_score(prices, as_of) if prices else 0
    sec = sector_tailwind_score(None, as_of)
    gov = governance_safety_score(fins)

    latest_q = fins[0] if fins else None
    latest_a = next((f for f in fins if f.period_type == "annual"), None)
    eq = evidence_quality_score(
        as_of_date=as_of,
        latest_quarterly=latest_q,
        latest_annual=latest_a,
        cohort_size=None,
        last_4_quarters_complete=len([f for f in fins if f.period_type == "quarterly"]) >= 4,
    )

    subs = SubScores(
        cea_score=cea_score,
        earnings_acceleration_score=ea,
        business_quality_score=bq,
        governance_safety_score=gov,
        valuation_sanity_score=vs,
        technical_confirmation_score=tc,
        sector_tailwind_score=sec,
        liquidity_score=liq,
        evidence_quality_score=eq,
    )
    return subs, eq


def _portfolio_context(session: Session, regime: str) -> PortfolioContext:
    holdings = session.execute(select(PortfolioHolding)).scalars().all()
    records = [
        HoldingRecord(
            company_id=h.company_id,
            symbol=h.symbol,
            mbs_final=int(round((h.portfolio_weight or 0.0) * 100)),  # placeholder until per-holding scoring
            position_pct=float(h.portfolio_weight or 0.0),
            thesis_status=h.thesis_status,
        )
        for h in holdings
    ]
    return PortfolioContext(
        holdings=records,
        holdings_count=len(records),
        max_single_position_pct=max((r.position_pct for r in records), default=0.0),
        max_sector_concentration_pct=0.0,  # computed elsewhere; placeholder for v1
        rolling_12m_turnover=0.0,
        has_unstarted_broken_exit=any(r.thesis_status == "broken" for r in records),
        market_regime=regime,
    )


def run_monthly_cycle(
    session: Session,
    *,
    as_of_date: date,
    monthly_capital: int = 25_000,
    benchmark_index: str = "NIFTY_500_TRI",
    universe_index: str = "NIFTY_500",
    cohort_observation_step_days: int = 60,
) -> CycleResult:
    """Compute the monthly deployment plan and persist it.

    Steps mirror the scoring_methodology.md walk-through (section 8):
      1. Universe at as_of_date (PIT-correct).
      2. For each candidate compute sub-scores (CEA via the cohort builder).
      3. Monthly Buy Score per candidate.
      4. Portfolio Edge Score across the candidate set + portfolio context.
      5. Deployment plan with whole-share rounding.
      6. Persist plan, actions, and historical_predictions.
    """
    regime_fn = make_regime_fn(session, benchmark_index)
    bench_fn = make_benchmark_return_fn(session, benchmark_index)
    regime = regime_fn(as_of_date)

    universe = get_universe_at(session, as_of_date)
    constituents = get_index_constituents_as_of(session, universe_index, as_of_date)
    if constituents:
        universe = universe & constituents

    candidate_records: list[CandidateRecord] = []
    deployment_candidates: list[CandidateForDeployment] = []
    prediction_payloads: list[tuple[int, str, int, int, str, int, dict, str]] = []

    for company_id in sorted(universe):
        meta = get_company_metadata(session, company_id)
        if meta is None:
            continue

        observations = build_cohort(
            session,
            candidate_id=company_id,
            as_of_date=as_of_date,
            regime_at=regime_fn,
            benchmark_return=bench_fn,
            observation_step_days=cohort_observation_step_days,
        )
        cohort_stats = compute_cohort_stats(observations)
        cea = cohort_stats.cea_score

        subs, eq = _compute_subscores(session, company_id, as_of_date, cea)
        result = monthly_buy_score(subs, fatal_governance=False)

        prices = get_prices_until(session, company_id, as_of_date)
        last_price = prices[-1].close if prices else 0.0

        candidate_records.append(
            CandidateRecord(
                company_id=company_id,
                symbol=meta.symbol,
                mbs_final=result.mbs_final,
                evidence_quality=eq,
                is_strong=result.mbs_final >= 70 and eq >= 40 and result.classification == "candidate",
            )
        )
        deployment_candidates.append(
            CandidateForDeployment(
                company_id=company_id,
                symbol=meta.symbol,
                mbs_final=result.mbs_final,
                last_price=last_price,
                is_strong=result.mbs_final >= 70 and eq >= 40 and result.classification == "candidate",
                classification=result.classification,
            )
        )
        snapshot = {
            "company_id": company_id,
            "as_of_date": as_of_date,
            "subs": subs.__dict__,
            "cohort_size": cohort_stats.cohort_size,
            "cohort_median": cohort_stats.median_excess_return,
            "regime": regime,
        }
        snapshot_hash = feature_snapshot_hash(snapshot)
        prediction_payloads.append(
            (
                company_id,
                meta.symbol,
                result.mbs_final,
                0,  # PES filled in later, after compute_portfolio_edge_score
                result.classification,
                eq,
                {"subs": subs.__dict__, "cohort_size": cohort_stats.cohort_size},
                snapshot_hash,
            )
        )

    ctx = _portfolio_context(session, regime)
    edge = compute_portfolio_edge_score(candidate_records, ctx)
    split, actions = build_deployment_plan(monthly_capital, edge.pes, deployment_candidates)

    plan = MonthlyDeploymentPlan(
        rebalance_date=as_of_date,
        monthly_capital=monthly_capital,
        benchmark=benchmark_index,
        portfolio_edge_score=edge.pes,
        edge_breakdown_json={
            "active_opportunity_breadth": edge.active_opportunity_breadth,
            "top_candidate_quality": edge.top_candidate_quality,
            "evidence_quality_topn": edge.evidence_quality_topn,
            "market_regime_support": edge.market_regime_support,
            "existing_portfolio_add_opportunity": edge.existing_portfolio_add_opportunity,
            "risk_cost_penalty": edge.risk_cost_penalty,
            "regime": regime,
        },
        index_allocation=split.index_amount,
        active_allocation=split.active_amount,
    )
    session.add(plan)
    session.flush()

    for rank, action in enumerate(actions, start=1):
        session.add(
            MonthlyBuyAction(
                deployment_plan_id=plan.id,
                rank=rank,
                action_type=action.action_type,
                company_id=action.company_id,
                symbol=action.symbol,
                target_amount=action.target_amount,
                executable_quantity=action.executable_quantity,
                estimated_trade_value=action.estimated_trade_value,
                residual_amount=action.residual_amount,
                residual_destination=action.residual_destination,
                monthly_buy_score=None,
                reason=action.reason,
            )
        )

    for cid, sym, mbs, _, classification, _eq, sub_json, h in prediction_payloads:
        session.add(
            HistoricalPrediction(
                replay_date=as_of_date,
                company_id=cid,
                symbol=sym,
                monthly_buy_score=mbs,
                portfolio_edge_score=edge.pes,
                classification=classification,
                recommended_action="new_buy" if classification == "candidate" and mbs >= 70 else "hold",
                recommended_amount=0,
                benchmark=benchmark_index,
                feature_snapshot_hash=h,
                sub_scores_json=sub_json,
            )
        )

    return CycleResult(
        plan_id=plan.id,
        rebalance_date=as_of_date,
        pes=edge.pes,
        index_amount=split.index_amount,
        active_amount=split.active_amount,
        n_candidates_evaluated=len(candidate_records),
        n_strong_candidates=sum(1 for c in candidate_records if c.is_strong),
        n_actions=len(actions),
    )
