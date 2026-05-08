"""Phase 5-9 sub-score feature engines.

Each function consumes PIT loader output (never raw history) and produces
an integer score in [0, 100] consistent with scoring_methodology.md.
The scoring engine in `engines/monthly_buy.py` weights these sub-scores
into the Monthly Buy Score per scoring_methodology.md section 4.

Implementations are deliberately simple but real — they match the
spirit of the methodology doc with concrete thresholds, are PIT-safe,
and are deterministic. Refinement (e.g., sector adjustments) is an
expected source of strategy versions, not a v1 requirement.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..pit.point_in_time_loader import FinancialRow, PriceRow


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(round(max(lo, min(hi, value))))


def business_quality_score(financials: list[FinancialRow]) -> int:
    """Phase 5: composite of ROE (annualised), OCF/PAT (cash conversion), D/E.

    Inputs: list of FinancialRow with most recent first (per
    get_financials_available_until). Uses the 4 most recent quarterly
    rows (rolling TTM) when available; falls back to single-period if not.
    Returns 0 if data insufficient.
    """
    quarterly = [f for f in financials if f.period_type == "quarterly"]
    if not quarterly:
        return 0
    recent = quarterly[:4]
    pat = sum(r.pat for r in recent if r.pat is not None)
    nw = recent[0].net_worth or 0.0
    debt = recent[0].total_debt or 0.0
    ocf = sum(r.operating_cash_flow for r in recent if r.operating_cash_flow is not None)

    roe = (pat / nw) if nw and nw > 0 else 0.0
    ocf_pat = (ocf / pat) if pat and pat > 0 else 0.0
    de = (debt / nw) if nw and nw > 0 else 999.0

    # ROE component: 0 below 5%, 100 at 25%+, linear in between
    roe_pts = ((roe - 0.05) / 0.20) * 100
    # OCF/PAT: 0 at 0.3, 100 at 1.1+ (typical quality range)
    ocf_pts = ((ocf_pat - 0.3) / 0.8) * 100
    # D/E: 100 at 0, 0 at 1.5+ (penalise leverage)
    de_pts = (1.0 - (de / 1.5)) * 100

    composite = 0.40 * _clip(roe_pts) + 0.35 * _clip(ocf_pts) + 0.25 * _clip(de_pts)
    return _clip(composite)


def earnings_acceleration_score(financials: list[FinancialRow]) -> int:
    """Phase 7: revenue YoY trend across the last 4 quarters.

    Acceleration = recent YoY > older YoY. Score rewards positive,
    accelerating growth and penalises deceleration.
    """
    quarterly = sorted(
        (f for f in financials if f.period_type == "quarterly"),
        key=lambda f: f.period_end_date,
        reverse=True,
    )
    if len(quarterly) < 8:
        return 50  # insufficient history → neutral
    recent_4 = quarterly[:4]
    older_4 = quarterly[4:8]
    rev_recent = sum(r.revenue for r in recent_4 if r.revenue is not None)
    rev_older = sum(r.revenue for r in older_4 if r.revenue is not None)
    if rev_older <= 0:
        return 50
    yoy_recent = (rev_recent / rev_older) - 1.0

    # Compare the YoY of the most recent two quarters vs the older two
    rev_q1 = sum(r.revenue for r in recent_4[:2] if r.revenue is not None)
    rev_q2 = sum(r.revenue for r in recent_4[2:] if r.revenue is not None)
    rev_q3 = sum(r.revenue for r in older_4[:2] if r.revenue is not None)
    rev_q4 = sum(r.revenue for r in older_4[2:] if r.revenue is not None)
    yoy_recent_half = (rev_q1 / rev_q3 - 1.0) if rev_q3 > 0 else 0.0
    yoy_older_half = (rev_q2 / rev_q4 - 1.0) if rev_q4 > 0 else 0.0
    acceleration = yoy_recent_half - yoy_older_half

    growth_pts = ((yoy_recent + 0.05) / 0.30) * 100  # 0 at -5% YoY, 100 at +25% YoY
    accel_pts = (acceleration / 0.10) * 100 + 50  # 50 at flat, 100 at +10pp accel
    composite = 0.60 * _clip(growth_pts) + 0.40 * _clip(accel_pts)
    return _clip(composite)


def valuation_sanity_score(
    last_close: float, financials: list[FinancialRow], shares_out: float | None = None
) -> int:
    """Phase 6: simple P/E sanity score.

    100 at cheap (<15x); 0 at extreme (>60x). Without shares outstanding we
    use a TTM EPS estimate from the last 4 quarters (eps already aggregates
    per company; sum gives an annualised estimate).
    """
    quarterly = [f for f in financials if f.period_type == "quarterly"]
    if not quarterly:
        return 50
    recent = quarterly[:4]
    ttm_eps = sum(r.eps for r in recent if r.eps is not None)
    if ttm_eps <= 0:
        return 30  # loss-making penalised
    pe = last_close / ttm_eps
    # 100 below 15, 0 above 60, linear
    pts = (1.0 - (pe - 15) / 45) * 100
    return _clip(pts)


def technical_confirmation_score(prices: list[PriceRow], as_of_date: date) -> int:
    """Phase 8: above-200-DMA + drawdown from 52w high.

    Score components:
    - Above 200-day SMA: 60 if yes, 20 if no.
    - Drawdown from 52w high: -50% drawdown -> 0; 0 drawdown -> 40.
    """
    if not prices:
        return 0
    relevant = [p for p in prices if p.trade_date <= as_of_date]
    if len(relevant) < 200:
        return 40  # insufficient history → modestly favourable
    last = relevant[-1].close
    sma200 = sum(p.close for p in relevant[-200:]) / 200.0

    one_year_ago = as_of_date - timedelta(days=365)
    last_year = [p for p in relevant if p.trade_date >= one_year_ago]
    if not last_year:
        last_year = relevant
    high = max(p.high or p.close for p in last_year)
    drawdown = (last / high) - 1.0 if high > 0 else 0.0

    above_sma = 60 if last > sma200 else 20
    dd_pts = (1.0 + drawdown / 0.5) * 40  # drawdown=-50% -> 0; drawdown=0 -> 40
    return _clip(above_sma + dd_pts)


def liquidity_score(prices: list[PriceRow], as_of_date: date) -> int:
    """Phase 8 supplement: 30-day average daily traded value bucket.

    high (>= Rs 50 cr) -> 90; mid (Rs 5 cr - 50 cr) -> 70; low (< Rs 5 cr) -> 40.
    """
    relevant = [p for p in prices if p.trade_date <= as_of_date]
    last_30 = relevant[-30:]
    if not last_30:
        return 0
    turnovers = [p.turnover for p in last_30 if p.turnover is not None]
    if not turnovers:
        return 50
    adv = sum(turnovers) / len(turnovers)
    cr = adv / 1e7  # turnover stored in rupees; 1 cr = 1e7
    if cr >= 50:
        return 90
    if cr >= 5:
        return 70
    return 40


def liquidity_bucket(prices: list[PriceRow], as_of_date: date) -> str:
    """Categorical liquidity bucket for cohort matching (scoring_methodology.md section 3.1)."""
    relevant = [p for p in prices if p.trade_date <= as_of_date]
    last_30 = relevant[-30:]
    if not last_30:
        return "low"
    turnovers = [p.turnover for p in last_30 if p.turnover is not None]
    if not turnovers:
        return "low"
    adv = sum(turnovers) / len(turnovers)
    cr = adv / 1e7
    if cr >= 50:
        return "high"
    if cr >= 5:
        return "mid"
    return "low"


def sector_tailwind_score(sector: str | None, as_of_date: date) -> int:  # noqa: ARG001
    """Phase 9: sector-tailwind score. v1 stub returns neutral 50.

    Real implementation would consume sector indices and macro signals;
    not in v1 scope. The strategy_versions champion-challenger framework
    (Phase 17) is where sector-aware variants are explored.
    """
    return 50


def governance_safety_score(financials: list[FinancialRow]) -> int:
    """Phase 9 structured-tier governance safety.

    Penalises receivables-vs-revenue divergence and CFO/PAT erosion.
    Textual-tier flags are handled separately by the human-review gate
    (scoring_methodology.md section 9.1) and do not enter this score.
    """
    quarterly = sorted(
        (f for f in financials if f.period_type == "quarterly"),
        key=lambda f: f.period_end_date,
        reverse=True,
    )
    if len(quarterly) < 4:
        return 60
    score = 100.0

    # Receivables-vs-revenue: if receivables grow faster than revenue YoY, penalise.
    rec_recent = quarterly[0].receivables or 0.0
    rec_yo = quarterly[3].receivables if len(quarterly) >= 4 else 0.0
    rev_recent = quarterly[0].revenue or 0.0
    rev_yo = quarterly[3].revenue if len(quarterly) >= 4 else 0.0
    if rec_yo and rev_yo:
        rec_growth = (rec_recent / rec_yo) - 1.0
        rev_growth = (rev_recent / rev_yo) - 1.0
        gap = rec_growth - rev_growth
        if gap > 0.20:
            score -= 30

    # CFO/PAT trailing 4 quarters
    pat = sum(r.pat for r in quarterly[:4] if r.pat is not None)
    ocf = sum(r.operating_cash_flow for r in quarterly[:4] if r.operating_cash_flow is not None)
    if pat > 0:
        ratio = ocf / pat
        if ratio < 0.3:
            score -= 40
        elif ratio < 0.5:
            score -= 20

    return _clip(score)


def evidence_quality_score(
    *,
    as_of_date: date,
    latest_quarterly: FinancialRow | None,
    latest_annual: FinancialRow | None,
    cohort_size: int | None,
    has_low_tier_only_field: bool = False,
    has_unverified_text_fact: bool = False,
    has_value_conflict: bool = False,
    last_4_quarters_complete: bool = True,
) -> int:
    """Per scoring_methodology.md section 2.1.

    Start at 100 and apply deductions for stale data, missing fields,
    low-tier sources, conflicts, low cohort size, and unverified text.
    """
    score = 100

    if latest_quarterly is None or (as_of_date - latest_quarterly.announcement_date).days > 90:
        score -= 10
    if latest_annual is None or (as_of_date - latest_annual.announcement_date).days > 270:
        score -= 10
    if not last_4_quarters_complete:
        score -= 10
    if has_low_tier_only_field:
        score -= 10
    if has_value_conflict:
        score -= 10
    if cohort_size is not None:
        if cohort_size < 10:
            score -= 30
        elif cohort_size < 30:
            score -= 15
    if has_unverified_text_fact:
        score -= 10

    return max(0, score)
