"""Phase 11: Portfolio Edge Score engine.

Per scoring_methodology.md section 5:

  PES = 0.30 * Active_Opportunity_Breadth
      + 0.25 * Top_Candidate_Quality
      + 0.15 * Evidence_Quality_TopN
      + 0.10 * Market_Regime_Support
      + 0.10 * Existing_Portfolio_Add_Opportunity
      + 0.10 * Risk_Cost_Penalty
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateRecord:
    """A scored candidate, used for the breadth and top-N components."""

    company_id: int
    symbol: str
    mbs_final: int
    evidence_quality: int
    is_strong: bool  # MBS_final >= 70 AND no fatal AND E_Q >= 40 AND not capped


@dataclass(frozen=True)
class HoldingRecord:
    company_id: int
    symbol: str
    mbs_final: int
    position_pct: float  # 0..1 of portfolio NAV
    thesis_status: str  # "intact" | "weakening" | "broken"


@dataclass(frozen=True)
class PortfolioContext:
    holdings: list[HoldingRecord]
    holdings_count: int
    max_single_position_pct: float  # 0..1
    max_sector_concentration_pct: float  # 0..1
    rolling_12m_turnover: float  # 0..1+
    has_unstarted_broken_exit: bool
    market_regime: str  # "bull" | "neutral" | "bear"


@dataclass(frozen=True)
class EdgeScoreBreakdown:
    active_opportunity_breadth: int
    top_candidate_quality: int
    evidence_quality_topn: int
    market_regime_support: int
    existing_portfolio_add_opportunity: int
    risk_cost_penalty: int
    pes: int


def _breadth(strong_count: int) -> int:
    if strong_count == 0:
        return 0
    if strong_count == 1:
        return 40
    if strong_count <= 3:
        return 60
    if strong_count <= 6:
        return 80
    return 100


def _top5_mean(values: list[int]) -> int:
    if not values:
        return 0
    top5 = sorted(values, reverse=True)[:5]
    return int(round(sum(top5) / len(top5)))


def _regime_support(regime: str) -> int:
    return {"bull": 80, "neutral": 50, "bear": 20}.get(regime, 50)


def _existing_add_opportunity(holdings: list[HoldingRecord], cap_pct: float = 0.10) -> int:
    if not holdings:
        return 50  # cold-start neutral
    addable_scores = [
        h.mbs_final for h in holdings if h.position_pct < cap_pct and h.thesis_status == "intact"
    ]
    if not addable_scores:
        return 0
    return int(round(sum(addable_scores) / len(addable_scores)))


def _risk_cost_penalty(ctx: PortfolioContext) -> int:
    score = 100
    if ctx.holdings_count > 18:
        score -= 10 * (ctx.holdings_count - 18)
    if ctx.max_single_position_pct > 0.10:
        score -= 10
    if ctx.max_sector_concentration_pct > 0.25:
        score -= 10
    if ctx.rolling_12m_turnover > 1.0:
        score -= 20
    if ctx.has_unstarted_broken_exit:
        score -= 15
    return max(0, score)


def compute_portfolio_edge_score(
    candidates: list[CandidateRecord], ctx: PortfolioContext
) -> EdgeScoreBreakdown:
    strong = [c for c in candidates if c.is_strong]
    breadth = _breadth(len(strong))
    top5_mbs = _top5_mean([c.mbs_final for c in strong])
    top5_eq = _top5_mean([c.evidence_quality for c in strong])
    regime = _regime_support(ctx.market_regime)
    add_opp = _existing_add_opportunity(ctx.holdings)
    risk = _risk_cost_penalty(ctx)

    pes_raw = (
        0.30 * breadth
        + 0.25 * top5_mbs
        + 0.15 * top5_eq
        + 0.10 * regime
        + 0.10 * add_opp
        + 0.10 * risk
    )
    pes = int(round(max(0.0, min(100.0, pes_raw))))

    return EdgeScoreBreakdown(
        active_opportunity_breadth=breadth,
        top_candidate_quality=top5_mbs,
        evidence_quality_topn=top5_eq,
        market_regime_support=regime,
        existing_portfolio_add_opportunity=add_opp,
        risk_cost_penalty=risk,
        pes=pes,
    )
