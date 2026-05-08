"""Phase 10-12 engine tests: cohort expected alpha, monthly buy score,
portfolio edge score, deployment engine."""

from __future__ import annotations

from datetime import date

import pytest

from india_monthly_alpha_engine.engines.cohort_expected_alpha import (
    CohortObservation,
    compute_cohort_stats,
)
from india_monthly_alpha_engine.engines.deployment import (
    CandidateForDeployment,
    allocate_active,
    build_deployment_plan,
    split_by_pes,
)
from india_monthly_alpha_engine.engines.monthly_buy import (
    SubScores,
    monthly_buy_score,
)
from india_monthly_alpha_engine.engines.portfolio_edge import (
    CandidateRecord,
    HoldingRecord,
    PortfolioContext,
    compute_portfolio_edge_score,
)

# Cohort engine ------------------------------------------------------------


def test_cohort_stats_high_confidence_positive_median() -> None:
    obs = [
        CohortObservation(company_id=i, observation_date=date(2018, 1, 1), forward_excess_return_12m=v)
        for i, v in enumerate(
            [0.10, 0.05, 0.20, 0.08, 0.12, 0.06, 0.15, 0.11, 0.07, 0.09] * 3
        )
    ]
    stats = compute_cohort_stats(obs)
    assert stats.cohort_size == 30
    assert stats.cea_score >= 70
    assert stats.median_excess_return > 0
    assert stats.hit_rate == 1.0


def test_cohort_stats_zero_when_too_small() -> None:
    obs = [
        CohortObservation(company_id=i, observation_date=date(2018, 1, 1), forward_excess_return_12m=0.20)
        for i in range(5)
    ]
    stats = compute_cohort_stats(obs)
    assert stats.cohort_size == 5
    assert stats.cea_score == 0  # cohort < 10 -> 0


def test_cohort_stats_capped_at_60_for_medium_confidence() -> None:
    obs = [
        CohortObservation(company_id=i, observation_date=date(2018, 1, 1), forward_excess_return_12m=0.50)
        for i in range(15)
    ]
    stats = compute_cohort_stats(obs)
    assert stats.cohort_size == 15
    # Raw would be 50 + 250*0.5 = 175 -> clip to 100; cap to 60
    assert stats.cea_score == 60


def test_cohort_stats_clip_zero_for_negative_median() -> None:
    obs = [
        CohortObservation(company_id=i, observation_date=date(2018, 1, 1), forward_excess_return_12m=-0.30)
        for i in range(40)
    ]
    stats = compute_cohort_stats(obs)
    assert stats.median_excess_return == -0.30
    assert stats.cea_score == 0


def test_cohort_stats_empty() -> None:
    stats = compute_cohort_stats([])
    assert stats.cohort_size == 0
    assert stats.cea_score == 0


# Monthly Buy Score --------------------------------------------------------


def _subs(eq: int = 100, **overrides: int) -> SubScores:
    base = {
        "cea_score": 65,
        "earnings_acceleration_score": 75,
        "business_quality_score": 70,
        "governance_safety_score": 85,
        "valuation_sanity_score": 55,
        "technical_confirmation_score": 70,
        "sector_tailwind_score": 60,
        "liquidity_score": 75,
        "evidence_quality_score": eq,
    }
    base.update(overrides)
    return SubScores(**base)


def test_monthly_buy_score_typical() -> None:
    """Reproduces the worked example from scoring_methodology.md section 8."""
    result = monthly_buy_score(_subs(eq=100), fatal_governance=False)
    # 0.20*65 + 0.15*75 + 0.15*70 + 0.15*85 + 0.12*55 + 0.08*70 + 0.05*60 + 0.05*75 + 0.05*100
    # = 13 + 11.25 + 10.5 + 12.75 + 6.6 + 5.6 + 3 + 3.75 + 5 = 71.45
    assert result.mbs_raw == pytest.approx(71.45, abs=0.01)
    # E_Q multiplier 1.0 -> mbs_final = round(71.45) = 71
    assert result.e_q_multiplier == 1.0
    assert result.mbs_final == 71
    assert result.classification == "candidate"


def test_monthly_buy_score_eq_multiplier_caps_low_evidence() -> None:
    result = monthly_buy_score(_subs(eq=0), fatal_governance=False)
    # E_Q multiplier 0.5 halves the final score
    assert result.e_q_multiplier == 0.5
    assert result.mbs_final < result.mbs_raw / 1.5


def test_monthly_buy_score_fatal_governance_zero() -> None:
    result = monthly_buy_score(_subs(eq=100), fatal_governance=True)
    assert result.mbs_final == 0
    assert result.classification == "reject"
    assert result.reject_reason == "fatal_governance_structured"


# Portfolio Edge Score -----------------------------------------------------


def _candidate(mbs: int, eq: int = 90, *, strong: bool = True) -> CandidateRecord:
    return CandidateRecord(
        company_id=mbs,  # arbitrary
        symbol=f"SYM{mbs}",
        mbs_final=mbs,
        evidence_quality=eq,
        is_strong=strong and mbs >= 70 and eq >= 40,
    )


def _ctx(holdings: list[HoldingRecord] | None = None, *, regime: str = "neutral") -> PortfolioContext:
    return PortfolioContext(
        holdings=holdings or [],
        holdings_count=len(holdings) if holdings else 0,
        max_single_position_pct=0.08,
        max_sector_concentration_pct=0.22,
        rolling_12m_turnover=0.35,
        has_unstarted_broken_exit=False,
        market_regime=regime,
    )


def test_portfolio_edge_score_worked_example() -> None:
    """Reproduces scoring_methodology.md section 8 example."""
    cands = [_candidate(78), _candidate(74), _candidate(71), _candidate(68, strong=False), _candidate(65, strong=False)]
    holdings = [
        HoldingRecord(company_id=i, symbol=f"H{i}", mbs_final=60, position_pct=0.07, thesis_status="intact")
        for i in range(14)
    ]
    breakdown = compute_portfolio_edge_score(cands, _ctx(holdings, regime="neutral"))
    # 3 strong -> breadth=60; top5 mean = (78+74+71+68+65)/5 = 71.2 -> 71
    assert breakdown.active_opportunity_breadth == 60
    assert breakdown.market_regime_support == 50
    assert breakdown.existing_portfolio_add_opportunity == 60
    assert breakdown.risk_cost_penalty == 100
    # 0.30*60 + 0.25*71 + 0.15*92 + 0.10*50 + 0.10*60 + 0.10*100 ≈ 70.55 -> 71
    assert breakdown.pes == 71


def test_portfolio_edge_score_no_candidates() -> None:
    breakdown = compute_portfolio_edge_score([], _ctx(regime="neutral"))
    assert breakdown.active_opportunity_breadth == 0
    assert breakdown.top_candidate_quality == 0


def test_portfolio_edge_score_bear_regime_drags() -> None:
    cands = [_candidate(80) for _ in range(8)]
    bull = compute_portfolio_edge_score(cands, _ctx(regime="bull"))
    bear = compute_portfolio_edge_score(cands, _ctx(regime="bear"))
    assert bull.pes > bear.pes


def test_portfolio_edge_score_bloat_penalises_risk() -> None:
    holdings = [
        HoldingRecord(company_id=i, symbol=f"H{i}", mbs_final=50, position_pct=0.05, thesis_status="intact")
        for i in range(25)  # > 18
    ]
    cands = [_candidate(80) for _ in range(5)]
    breakdown = compute_portfolio_edge_score(cands, _ctx(holdings, regime="neutral"))
    assert breakdown.risk_cost_penalty < 100


# Deployment ---------------------------------------------------------------


def test_split_by_pes_table() -> None:
    assert split_by_pes(25_000, 30) == split_by_pes(25_000, 30)
    assert split_by_pes(25_000, 30).index_amount == 25_000
    assert split_by_pes(25_000, 55).index_amount == 20_000
    assert split_by_pes(25_000, 65).index_amount == 15_000
    assert split_by_pes(25_000, 75).index_amount == 10_000
    assert split_by_pes(25_000, 85).index_amount == 5_000
    assert split_by_pes(25_000, 95).index_amount == 5_000  # 20% floor
    assert split_by_pes(25_000, 100).index_amount == 5_000  # 20% floor


def test_allocate_active_whole_share_rounding() -> None:
    cands = [
        CandidateForDeployment(company_id=1, symbol="X", mbs_final=80, last_price=2800.0, is_strong=True, classification="candidate"),
    ]
    actions, residual = allocate_active(5000, cands, ticket_cap=5000, ticket_floor=2500)
    # 5000 / 2800 -> 1 share = 2800; residual = 2200
    assert len(actions) == 1
    assert actions[0].executable_quantity == 1
    assert actions[0].estimated_trade_value == 2800.0
    assert actions[0].residual_amount == 2200
    # remaining after the buy = 5000 - 2800 = 2200, below ticket_floor -> spill to index
    assert residual == 2200


def test_allocate_active_skips_too_expensive_stock() -> None:
    cands = [
        CandidateForDeployment(company_id=1, symbol="EXP", mbs_final=85, last_price=10000.0, is_strong=True, classification="candidate"),
    ]
    actions, residual = allocate_active(2500, cands, ticket_cap=5000, ticket_floor=2500)
    # 2500 < 10000; spills the whole 2500 to index
    assert actions[0].action_type == "hold_cash"
    assert actions[0].residual_destination == "index"
    assert residual == 0


def test_build_deployment_plan_low_pes_all_index() -> None:
    cands = [
        CandidateForDeployment(company_id=1, symbol="X", mbs_final=85, last_price=300.0, is_strong=True, classification="candidate"),
    ]
    split, actions = build_deployment_plan(25_000, 40, cands)
    assert split.index_amount == 25_000
    assert split.active_amount == 0
    # Single buy_index action only
    assert all(a.action_type in {"buy_index"} for a in actions)


def test_build_deployment_plan_strong_pes_active_dominates() -> None:
    cands = [
        CandidateForDeployment(company_id=i, symbol=f"S{i}", mbs_final=80 + i, last_price=300.0, is_strong=True, classification="candidate")
        for i in range(5)
    ]
    split, actions = build_deployment_plan(25_000, 85, cands)
    assert split.index_amount == 5_000
    assert split.active_amount == 20_000
    new_buys = [a for a in actions if a.action_type == "new_buy"]
    assert len(new_buys) >= 4
    index_action = next(a for a in actions if a.action_type == "buy_index")
    assert index_action.target_amount >= 5_000  # floor + active residual
