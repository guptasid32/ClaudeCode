"""Phase 14-18 tests: validity tools, monthly report, mistake analyzer,
champion-challenger."""

from __future__ import annotations

from datetime import date

import pytest

from india_monthly_alpha_engine.backtest.bootstrap import block_bootstrap_mean
from india_monthly_alpha_engine.backtest.calibration import (
    bucket_calibration,
    decile_monotonicity,
)
from india_monthly_alpha_engine.backtest.survivorship_analysis import (
    compute_survivorship_gap,
)
from india_monthly_alpha_engine.engines.deployment import build_deployment_plan
from india_monthly_alpha_engine.engines.portfolio_edge import (
    EdgeScoreBreakdown,
)
from india_monthly_alpha_engine.historical.champion_challenger import (
    StrategyEvaluation,
    holdout_decision,
    passes_validation,
    pre_register_holdout_candidate,
)
from india_monthly_alpha_engine.historical.mistake_analyzer import (
    HistoricalCase,
    analyze,
)
from india_monthly_alpha_engine.reports.monthly_deployment_report import (
    render_monthly_report,
)


def test_block_bootstrap_returns_ci_around_mean() -> None:
    returns = [0.01, -0.02, 0.03, 0.005, 0.008, -0.01, 0.015, 0.02, -0.005, 0.012] * 12
    ci = block_bootstrap_mean(returns, block_length=12, resamples=2000, seed=42)
    assert ci.lower <= ci.point_estimate <= ci.upper


def test_block_bootstrap_deterministic_with_seed() -> None:
    returns = [0.01, -0.02, 0.03, 0.005, 0.008, -0.01, 0.015, 0.02, -0.005, 0.012] * 12
    a = block_bootstrap_mean(returns, resamples=500, seed=7)
    b = block_bootstrap_mean(returns, resamples=500, seed=7)
    assert a.point_estimate == b.point_estimate
    assert a.lower == b.lower
    assert a.upper == b.upper


def test_bucket_calibration_monotonic_when_pes_predicts() -> None:
    pes = [40, 55, 65, 75, 85, 95] * 5
    fxr = [-0.05, -0.01, 0.01, 0.03, 0.06, 0.08] * 5
    result = bucket_calibration(pes, fxr)
    assert result.monotonic is True
    assert result.spread_top_minus_bottom > 0


def test_bucket_calibration_fails_when_random() -> None:
    pes = [40, 95, 55, 65, 85, 75]
    fxr = [0.10, -0.05, 0.08, 0.01, 0.03, 0.02]
    result = bucket_calibration(pes, fxr)
    assert result.monotonic is False


def test_decile_monotonicity_with_predictive_score() -> None:
    scores = list(range(100))  # 100 candidates
    fxr = [s * 0.001 for s in scores]  # forward return monotonically increases with score
    result = decile_monotonicity(scores, fxr)
    assert result.monotonic is True
    assert result.spearman_rho == pytest.approx(1.0, abs=1e-9)


def test_decile_monotonicity_with_non_predictive_score() -> None:
    """A score that anti-correlates with forward return must fail monotonicity."""
    scores = list(range(100))
    fxr = [(99 - s) * 0.001 for s in scores]  # decile means decrease in score order
    result = decile_monotonicity(scores, fxr)
    assert result.monotonic is False
    assert result.spearman_rho < 0


def test_survivorship_gap_warning_when_too_small() -> None:
    g = compute_survivorship_gap(survivor_only_cagr=0.155, survivorship_correct_cagr=0.150)
    assert g.gap_pp == pytest.approx(0.5, abs=1e-6)
    assert g.coverage_warning is not None


def test_survivorship_gap_no_warning_when_meaningful() -> None:
    g = compute_survivorship_gap(0.16, 0.13)
    assert g.gap_pp == pytest.approx(3.0, abs=1e-6)
    assert g.coverage_warning is None


def test_monthly_report_low_pes_explains_index_only() -> None:
    edge = EdgeScoreBreakdown(0, 0, 0, 50, 50, 100, 30)
    split, actions = build_deployment_plan(25_000, 30, [])
    report = render_monthly_report(rebalance_date=date(2024, 6, 30), split=split, actions=actions, edge=edge)
    assert "Portfolio Edge Score: 30" in report
    assert "Active allocation: Rs 0" in report
    assert "All Rs 25,000 went to the index leg" in report


def test_passes_validation_gates() -> None:
    good = StrategyEvaluation(
        strategy_name="hybrid_balanced",
        strategy_version="v0.1.0",
        net_cagr_excess_pp=2.5,
        bootstrap_lower_pp=0.5,
        style_alpha_pp=1.2,
        max_drawdown_relative_pp=2.0,
        longest_underperf_months=12,
    )
    ok, reasons = passes_validation(good)
    assert ok
    assert reasons == []


def test_passes_validation_blocks_drawdown_blowout() -> None:
    bad = StrategyEvaluation(
        strategy_name="quality_heavy",
        strategy_version="v0.1.0",
        net_cagr_excess_pp=2.0,
        bootstrap_lower_pp=0.3,
        style_alpha_pp=1.0,
        max_drawdown_relative_pp=10.0,  # > 5pp ceiling
        longest_underperf_months=8,
    )
    ok, reasons = passes_validation(bad)
    assert not ok
    assert any("max drawdown" in r for r in reasons)


def test_pre_register_picks_best_validated() -> None:
    a = StrategyEvaluation("a", "v1", 1.6, 0.1, 0.5, 1.0, 6)
    b = StrategyEvaluation("b", "v1", 3.0, 1.0, 1.5, 2.0, 12)
    c = StrategyEvaluation("c", "v1", 0.5, -0.5, 0.0, 1.0, 4)  # fails
    rec = pre_register_holdout_candidate([a, b, c])
    assert rec.pre_registered_strategy == "b@v1"
    assert "a@v1" in rec.validation_passers
    assert "b@v1" in rec.validation_passers


def test_pre_register_no_passer() -> None:
    weak = StrategyEvaluation("w", "v1", 0.5, -0.2, -0.1, 1.0, 30)
    rec = pre_register_holdout_candidate([weak])
    assert rec.pre_registered_strategy is None


def test_holdout_decision_pit_anomaly_burns() -> None:
    e = StrategyEvaluation("a", "v1", 2.0, 0.5, 1.0, 2.0, 6)
    decision = holdout_decision(e, pit_anomalies=True)
    assert not decision.promoted
    assert "PIT" in decision.reason


def test_holdout_decision_promotes_clean() -> None:
    e = StrategyEvaluation("a", "v1", 2.0, 0.5, 1.0, 2.0, 6)
    decision = holdout_decision(e)
    assert decision.promoted


def test_mistake_analyzer_pending_eval() -> None:
    cases = [
        HistoricalCase(
            company_id=1,
            symbol="X",
            sector="IT",
            strategy_version_id=1,
            monthly_buy_score=80,
            classification="candidate",
            forward_return_12m=None,
            benchmark_return_12m=None,
        )
    ]
    rep = analyze(cases)
    assert rep.n_evaluated == 0
    assert rep.n_pending == 1


def test_mistake_analyzer_flags_false_positives_and_misses() -> None:
    cases = [
        HistoricalCase(1, "BUY1", "IT", 1, 80, "candidate", -0.20, 0.05),  # FP
        HistoricalCase(2, "BUY2", "IT", 1, 75, "candidate", 0.10, 0.05),
        HistoricalCase(3, "REJ1", "FIN", 1, 50, "reject", 0.15, 0.05),  # missed
        HistoricalCase(4, "REJ2", "FIN", 1, 55, "reject", 0.04, 0.05),
    ]
    rep = analyze(cases)
    assert rep.n_evaluated == 4
    assert rep.false_positives == 1
    assert rep.missed_opportunities == 1
    assert rep.by_sector_excess_return["IT"] == pytest.approx((-0.25 + 0.05) / 2)
