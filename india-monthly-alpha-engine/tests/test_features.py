"""Phase 4-9 feature engine tests.

Covers adjusted prices (Phase 4) and the seven scoring sub-score
features (Phases 5-9). Tests are pure; they consume PIT-shaped
inputs without DB.
"""

from __future__ import annotations

from datetime import date

import pytest

from india_monthly_alpha_engine.features.adjusted_prices import (
    compute_adjusted_close,
    total_return,
)
from india_monthly_alpha_engine.features.scoring_features import (
    business_quality_score,
    earnings_acceleration_score,
    evidence_quality_score,
    governance_safety_score,
    liquidity_bucket,
    liquidity_score,
    sector_tailwind_score,
    technical_confirmation_score,
    valuation_sanity_score,
)
from india_monthly_alpha_engine.pit.point_in_time_loader import (
    CorporateActionRow,
    FinancialRow,
    PriceRow,
)


def _price(d: date, close: float, *, high: float | None = None, turnover: float | None = None) -> PriceRow:
    return PriceRow(
        trade_date=d,
        open=close,
        high=high or close,
        low=close,
        close=close,
        adjusted_close=close,
        volume=1000,
        delivery_volume=500,
        delivery_percentage=50.0,
        turnover=turnover,
    )


_QUARTER_END = (date(1, 3, 31), date(1, 6, 30), date(1, 9, 30), date(1, 12, 31))


def _qe(year: int, q: int) -> date:
    e = _QUARTER_END[q - 1]
    return date(year, e.month, e.day)


def _qa(year: int, q: int) -> date:
    months = (4, 7, 10, 1)
    days = (15, 15, 15, 15)
    if q == 4:
        return date(year + 1, months[q - 1], days[q - 1])
    return date(year, months[q - 1], days[q - 1])


def _fin(
    pe: date,
    aka: date,
    *,
    revenue: float = 100.0,
    pat: float = 15.0,
    ocf: float = 14.0,
    debt: float = 20.0,
    nw: float = 80.0,
    eps: float = 5.0,
    receivables: float = 10.0,
    period_type: str = "quarterly",
    fiscal_year: int = 2024,
    fiscal_quarter: int = 4,
) -> FinancialRow:
    return FinancialRow(
        period_type=period_type,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_end_date=pe,
        announcement_date=aka,
        as_known_at=aka,
        revenue=revenue,
        ebitda=None,
        ebit=None,
        pat=pat,
        eps=eps,
        total_assets=None,
        total_debt=debt,
        cash=None,
        net_worth=nw,
        operating_cash_flow=ocf,
        free_cash_flow=None,
        capex=None,
        receivables=receivables,
        inventory=None,
        payables=None,
    )


# Adjusted prices ----------------------------------------------------------


def test_adjusted_close_split_continuity() -> None:
    """1:2 split (numerator=1 old, denominator=2 new) halves pre-ex prices."""
    prices = [
        _price(date(2018, 6, 1), 1000.0),
        _price(date(2018, 6, 4), 500.0),  # ex-split day
        _price(date(2018, 6, 5), 510.0),
    ]
    actions = [
        CorporateActionRow(
            ex_date=date(2018, 6, 4),
            announcement_date=date(2018, 4, 19),
            action_type="split",
            ratio_numerator=1.0,  # old shares
            ratio_denominator=2.0,  # new shares
            cash_amount=None,
        )
    ]
    adj = compute_adjusted_close(prices, actions)
    assert adj[0].adjusted_close == pytest.approx(500.0, abs=1e-6)
    assert adj[1].adjusted_close == pytest.approx(500.0, abs=1e-6)
    assert adj[2].adjusted_close == pytest.approx(510.0, abs=1e-6)


def test_adjusted_close_bonus_continuity() -> None:
    """1:1 bonus: 1 new bonus share per 1 old; pre-ex prices halved."""
    prices = [
        _price(date(2024, 1, 1), 200.0),
        _price(date(2024, 10, 28), 100.0),
    ]
    actions = [
        CorporateActionRow(
            ex_date=date(2024, 10, 28),
            announcement_date=date(2024, 9, 5),
            action_type="bonus",
            ratio_numerator=1.0,
            ratio_denominator=1.0,
            cash_amount=None,
        )
    ]
    adj = compute_adjusted_close(prices, actions)
    assert adj[0].adjusted_close == pytest.approx(100.0)
    assert adj[1].adjusted_close == pytest.approx(100.0)


def test_adjusted_close_dividend_subtracts_from_pre_ex() -> None:
    prices = [
        _price(date(2024, 6, 20), 4000.0),
        _price(date(2024, 6, 21), 3927.0),
    ]
    actions = [
        CorporateActionRow(
            ex_date=date(2024, 6, 21),
            announcement_date=date(2024, 4, 12),
            action_type="dividend",
            ratio_numerator=None,
            ratio_denominator=None,
            cash_amount=73.0,
        )
    ]
    adj = compute_adjusted_close(prices, actions)
    # Pre-ex adjusted close = 4000 * (4000-73)/4000 = 3927
    assert adj[0].adjusted_close == pytest.approx(3927.0, abs=1e-3)
    assert adj[1].adjusted_close == pytest.approx(3927.0)


def test_unsupported_corporate_action_raises() -> None:
    prices = [_price(date(2024, 1, 1), 100.0)]
    actions = [
        CorporateActionRow(
            ex_date=date(2024, 6, 1),
            announcement_date=date(2024, 5, 1),
            action_type="merger",
            ratio_numerator=None,
            ratio_denominator=None,
            cash_amount=None,
        )
    ]
    with pytest.raises(NotImplementedError, match="merger"):
        compute_adjusted_close(prices, actions)


def test_total_return_uses_adjusted_close() -> None:
    prices = [
        _price(date(2024, 1, 1), 100.0),
        _price(date(2024, 12, 31), 120.0),
    ]
    assert total_return(prices) == pytest.approx(0.20)


# Scoring features ---------------------------------------------------------


def test_business_quality_score_high_quality() -> None:
    fins = [
        _fin(
            _qe(2024, q),
            _qa(2024, q),
            revenue=200.0,
            pat=40.0,  # 4 quarters * 40 = 160; ROE = 160/400 = 40%
            ocf=44.0,  # OCF/PAT = 1.1
            debt=50.0,
            nw=400.0,  # D/E = 0.125
            fiscal_quarter=q,
        )
        for q in (1, 2, 3, 4)
    ]
    score = business_quality_score(fins)
    assert score >= 80


def test_business_quality_score_low_quality() -> None:
    fins = [
        _fin(
            _qe(2024, q),
            _qa(2024, q),
            pat=2.0,
            ocf=1.0,  # poor cash conversion
            debt=400.0,
            nw=100.0,  # high leverage
            fiscal_quarter=q,
        )
        for q in (1, 2, 3, 4)
    ]
    score = business_quality_score(fins)
    assert score < 40


def test_earnings_acceleration_score_accelerating() -> None:
    # Build 8 quarters with accelerating revenue (recent 4 grow faster YoY)
    fins = []
    revs_recent = (260.0, 240.0, 220.0, 200.0)  # most recent first; descending in time order
    revs_older = (130.0, 120.0, 110.0, 100.0)
    for q, rev in zip((4, 3, 2, 1), revs_recent, strict=True):
        fins.append(_fin(_qe(2024, q), _qa(2024, q), revenue=rev, fiscal_quarter=q, fiscal_year=2024))
    for q, rev in zip((4, 3, 2, 1), revs_older, strict=True):
        fins.append(_fin(_qe(2023, q), _qa(2023, q), revenue=rev, fiscal_quarter=q, fiscal_year=2023))
    score = earnings_acceleration_score(fins)
    assert score > 60


def test_earnings_acceleration_neutral_when_insufficient_history() -> None:
    fins = [_fin(date(2024, 3, 31), date(2024, 4, 12))]
    assert earnings_acceleration_score(fins) == 50


def test_valuation_sanity_score_cheap_high_score() -> None:
    fins = [_fin(_qe(2024, q), _qa(2024, q), eps=10.0, fiscal_quarter=q) for q in (1, 2, 3, 4)]
    # ttm eps = 40; price 400 -> P/E = 10 -> high score
    score = valuation_sanity_score(400.0, fins)
    assert score >= 90


def test_valuation_sanity_score_expensive_low_score() -> None:
    fins = [_fin(_qe(2024, q), _qa(2024, q), eps=10.0, fiscal_quarter=q) for q in (1, 2, 3, 4)]
    # ttm eps = 40; price 4000 -> P/E = 100 -> low score
    score = valuation_sanity_score(4000.0, fins)
    assert score == 0


def test_technical_confirmation_above_sma_high_score() -> None:
    # 220 days of rising prices
    prices = [_price(date(2024, 1, 1) + __import__("datetime").timedelta(days=i), 100.0 + i * 0.5) for i in range(220)]
    score = technical_confirmation_score(prices, prices[-1].trade_date)
    assert score > 60


def test_technical_confirmation_below_sma_low_score() -> None:
    import datetime as dt
    prices = []
    for i in range(220):
        # First half rising to 200, second half falling to 100
        d = date(2024, 1, 1) + dt.timedelta(days=i)
        close = 100.0 + i if i < 110 else 210.0 - (i - 110)
        prices.append(_price(d, close, high=close + 5))
    score = technical_confirmation_score(prices, prices[-1].trade_date)
    assert score < 60


def test_liquidity_score_buckets() -> None:
    import datetime as dt
    base = date(2024, 1, 1)
    high_prices = [_price(base + dt.timedelta(days=i), 100.0, turnover=60e7) for i in range(40)]
    mid_prices = [_price(base + dt.timedelta(days=i), 100.0, turnover=10e7) for i in range(40)]
    low_prices = [_price(base + dt.timedelta(days=i), 100.0, turnover=1e7) for i in range(40)]

    assert liquidity_score(high_prices, base + dt.timedelta(days=39)) == 90
    assert liquidity_score(mid_prices, base + dt.timedelta(days=39)) == 70
    assert liquidity_score(low_prices, base + dt.timedelta(days=39)) == 40
    assert liquidity_bucket(high_prices, base + dt.timedelta(days=39)) == "high"
    assert liquidity_bucket(mid_prices, base + dt.timedelta(days=39)) == "mid"
    assert liquidity_bucket(low_prices, base + dt.timedelta(days=39)) == "low"


def test_sector_tailwind_default() -> None:
    assert sector_tailwind_score("IT", date(2024, 6, 30)) == 50


def test_governance_safety_full_score_when_clean() -> None:
    fins = [
        _fin(
            _qe(2024, q),
            _qa(2024, q),
            revenue=100.0,
            pat=10.0,
            ocf=12.0,  # OCF/PAT = 1.2
            receivables=10.0,
            fiscal_quarter=q,
        )
        for q in (1, 2, 3, 4)
    ]
    assert governance_safety_score(fins) == 100


def test_governance_safety_penalises_receivables_growth() -> None:
    fins = [
        _fin(date(2024, 12, 31), date(2025, 1, 15), revenue=110.0, receivables=30.0, fiscal_quarter=4),  # most recent
        _fin(date(2024, 9, 30), date(2024, 10, 15), revenue=105.0, receivables=20.0, fiscal_quarter=3),
        _fin(date(2024, 6, 30), date(2024, 7, 15), revenue=100.0, receivables=15.0, fiscal_quarter=2),
        _fin(date(2024, 3, 31), date(2024, 4, 15), revenue=100.0, receivables=10.0, fiscal_quarter=1),  # oldest
    ]
    assert governance_safety_score(fins) <= 70


def test_evidence_quality_perfect() -> None:
    fin = _fin(date(2024, 6, 30), date(2024, 7, 12))
    score = evidence_quality_score(
        as_of_date=date(2024, 8, 1),
        latest_quarterly=fin,
        latest_annual=fin,
        cohort_size=50,
    )
    assert score == 100


def test_evidence_quality_penalises_stale_and_small_cohort() -> None:
    fin = _fin(date(2024, 6, 30), date(2024, 7, 12))
    score = evidence_quality_score(
        as_of_date=date(2024, 12, 31),  # 6 months past quarterly announcement, > 90 days
        latest_quarterly=fin,
        latest_annual=fin,
        cohort_size=8,  # < 10 → -30
        has_low_tier_only_field=True,  # -10
    )
    # -10 quarterly stale - 30 cohort - 10 low tier = 50
    assert score == 50
