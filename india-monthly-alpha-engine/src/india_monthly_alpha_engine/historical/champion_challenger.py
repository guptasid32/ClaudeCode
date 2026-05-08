"""Phase 17: champion-challenger procedure.

Implements the validation gate, pre-registration, and single-shot
holdout test from backtest_validity_methodology.md section 7. Strategies
are passed in as already-evaluated bundles; this module makes the
gating decisions and produces a promotion recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyEvaluation:
    """Validation-set evaluation of a strategy."""

    strategy_name: str
    strategy_version: str
    net_cagr_excess_pp: float  # vs Nifty 500 TRI net
    bootstrap_lower_pp: float  # 95% block-bootstrap lower CI on monthly excess
    style_alpha_pp: float
    max_drawdown_relative_pp: float  # excess over benchmark drawdown
    longest_underperf_months: int


VALIDATION_GATES = {
    "min_cagr_excess_pp": 1.5,
    "min_bootstrap_lower_pp": 0.0,
    "min_style_alpha_pp": 0.0,
    "max_drawdown_excess_pp": 5.0,
    "max_underperf_months": 24,
}


def passes_validation(s: StrategyEvaluation) -> tuple[bool, list[str]]:
    """Returns (passed, reasons_for_failure)."""
    reasons: list[str] = []
    if s.net_cagr_excess_pp < VALIDATION_GATES["min_cagr_excess_pp"]:
        reasons.append(f"net CAGR excess {s.net_cagr_excess_pp:.2f}pp < 1.5pp")
    if s.bootstrap_lower_pp < VALIDATION_GATES["min_bootstrap_lower_pp"]:
        reasons.append(f"bootstrap lower CI {s.bootstrap_lower_pp:.2f}pp < 0")
    if s.style_alpha_pp < VALIDATION_GATES["min_style_alpha_pp"]:
        reasons.append(f"style-adjusted alpha {s.style_alpha_pp:.2f}pp < 0")
    if s.max_drawdown_relative_pp > VALIDATION_GATES["max_drawdown_excess_pp"]:
        reasons.append(
            f"max drawdown {s.max_drawdown_relative_pp:.1f}pp worse than benchmark + 5pp"
        )
    if s.longest_underperf_months > VALIDATION_GATES["max_underperf_months"]:
        reasons.append(f"underperf streak {s.longest_underperf_months}m > 24m")
    return (not reasons, reasons)


@dataclass(frozen=True)
class PromotionRecommendation:
    pre_registered_strategy: str | None
    validation_passers: list[str]
    rationale: str


def pre_register_holdout_candidate(
    evaluations: list[StrategyEvaluation],
) -> PromotionRecommendation:
    """Per backtest_validity_methodology.md section 7.3: among strategies that
    pass validation, pre-register the SINGLE best by net-of-cost-and-tax CAGR
    for the holdout test. Other passers are recorded but not retested."""
    passers = [(e, *passes_validation(e)) for e in evaluations]
    valid = [e for e, ok, _ in passers if ok]
    if not valid:
        return PromotionRecommendation(
            pre_registered_strategy=None,
            validation_passers=[],
            rationale="no strategy cleared the validation gate; champion stays",
        )
    winner = max(valid, key=lambda e: e.net_cagr_excess_pp)
    return PromotionRecommendation(
        pre_registered_strategy=f"{winner.strategy_name}@{winner.strategy_version}",
        validation_passers=[f"{e.strategy_name}@{e.strategy_version}" for e in valid],
        rationale=(
            f"pre-registered {winner.strategy_name}@{winner.strategy_version} "
            f"with {winner.net_cagr_excess_pp:.2f}pp net CAGR excess; "
            f"{len(valid)} strategy(ies) passed validation; "
            f"holdout will be tested ONCE on this single strategy"
        ),
    )


@dataclass(frozen=True)
class HoldoutDecision:
    promoted: bool
    reason: str


HOLDOUT_GATES = {
    "min_cagr_excess_pp": 0.0,  # any positive margin
    "min_bootstrap_lower_pp": 0.0,
    "min_style_alpha_pp": 0.0,
    "max_drawdown_excess_pp": 5.0,
}


def holdout_decision(holdout_eval: StrategyEvaluation, *, pit_anomalies: bool = False) -> HoldoutDecision:
    """Single-shot holdout decision per backtest_validity 7.4. If the strategy
    fails, NO other strategy is tested on this holdout (7.5)."""
    if pit_anomalies:
        return HoldoutDecision(promoted=False, reason="PIT-leakage anomaly detected; holdout burned")
    if holdout_eval.net_cagr_excess_pp < HOLDOUT_GATES["min_cagr_excess_pp"]:
        return HoldoutDecision(promoted=False, reason="negative net CAGR excess on holdout")
    if holdout_eval.bootstrap_lower_pp < HOLDOUT_GATES["min_bootstrap_lower_pp"]:
        return HoldoutDecision(promoted=False, reason="bootstrap lower CI below 0 on holdout")
    if holdout_eval.style_alpha_pp < HOLDOUT_GATES["min_style_alpha_pp"]:
        return HoldoutDecision(promoted=False, reason="style-adjusted alpha below 0 on holdout")
    if holdout_eval.max_drawdown_relative_pp > HOLDOUT_GATES["max_drawdown_excess_pp"]:
        return HoldoutDecision(
            promoted=False, reason="max drawdown >5pp worse than benchmark on holdout"
        )
    return HoldoutDecision(promoted=True, reason="all holdout gates cleared")
