"""Monthly Buy Score engine (scoring_methodology.md section 4).

MBS_raw = weighted sum of nine sub-scores; MBS_final = round(MBS_raw *
E_Q_multiplier) where E_Q_multiplier = 0.5 + 0.005 * E_Q. Fatal
governance flag forces MBS_final = 0 and classification = reject.
"""

from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {
    "cea": 0.20,
    "earnings_acceleration": 0.15,
    "business_quality": 0.15,
    "governance_safety": 0.15,
    "valuation_sanity": 0.12,
    "technical_confirmation": 0.08,
    "sector_tailwind": 0.05,
    "liquidity": 0.05,
    "evidence_quality": 0.05,
}


@dataclass(frozen=True)
class SubScores:
    cea_score: int
    earnings_acceleration_score: int
    business_quality_score: int
    governance_safety_score: int
    valuation_sanity_score: int
    technical_confirmation_score: int
    sector_tailwind_score: int
    liquidity_score: int
    evidence_quality_score: int


@dataclass(frozen=True)
class MonthlyBuyResult:
    mbs_raw: float
    mbs_final: int
    e_q_multiplier: float
    classification: str  # "candidate" | "reject"
    reject_reason: str | None


def monthly_buy_score(
    subs: SubScores, *, fatal_governance: bool, weights: dict[str, float] | None = None
) -> MonthlyBuyResult:
    """Compute Monthly Buy Score.

    `weights` lets champion-challenger strategies override the default
    weight set; if None, uses scoring_methodology.md section 4.1 defaults.
    """
    w = weights or WEIGHTS
    if fatal_governance:
        return MonthlyBuyResult(
            mbs_raw=0.0,
            mbs_final=0,
            e_q_multiplier=0.0,
            classification="reject",
            reject_reason="fatal_governance_structured",
        )

    mbs_raw = (
        w["cea"] * subs.cea_score
        + w["earnings_acceleration"] * subs.earnings_acceleration_score
        + w["business_quality"] * subs.business_quality_score
        + w["governance_safety"] * subs.governance_safety_score
        + w["valuation_sanity"] * subs.valuation_sanity_score
        + w["technical_confirmation"] * subs.technical_confirmation_score
        + w["sector_tailwind"] * subs.sector_tailwind_score
        + w["liquidity"] * subs.liquidity_score
        + w["evidence_quality"] * subs.evidence_quality_score
    )

    e_q_multiplier = 0.5 + 0.005 * subs.evidence_quality_score
    mbs_final = int(round(mbs_raw * e_q_multiplier))

    return MonthlyBuyResult(
        mbs_raw=mbs_raw,
        mbs_final=mbs_final,
        e_q_multiplier=e_q_multiplier,
        classification="candidate",
        reject_reason=None,
    )
