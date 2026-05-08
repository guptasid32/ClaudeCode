"""Phase 13 backtester tests + Phase 14 validity tests.

Covers cost model, tax model, FIFO lot accounting, and the monthly
SIP backtester end-to-end on a tiny synthetic dataset.
"""

from __future__ import annotations

from datetime import date

import pytest

from india_monthly_alpha_engine.backtest.cost_model import (
    compute_trade_cost,
    half_spread_per_side,
    round_trip_cost_pct,
)
from india_monthly_alpha_engine.backtest.monthly_sip_backtester import (
    MonthlyDecision,
    run_monthly_sip_backtest,
)
from india_monthly_alpha_engine.backtest.portfolio_lot_accounting import Lot, LotLedger
from india_monthly_alpha_engine.backtest.tax_model import (
    compute_tax_for_lot,
    fiscal_year_of,
    ltcg_exemption,
    ltcg_rate,
    regime_window,
    stcg_rate,
)

# Cost model ----


def test_trade_cost_zero_brokerage_and_components() -> None:
    c = compute_trade_cost(side="buy", trade_value=10_000, liquidity_bucket="high")
    # STT 0.10% = 10
    assert c.stt == pytest.approx(10.0)
    # Stamp 0.015% = 1.5
    assert c.stamp_duty == pytest.approx(1.5)
    # Exchange 0.00297% = 0.297
    assert c.exchange == pytest.approx(0.297, abs=1e-3)
    # SEBI 0.0001% = 0.01
    assert c.sebi == pytest.approx(0.01, abs=1e-4)
    # Brokerage zero in zero_delivery
    assert c.brokerage == 0.0
    # GST = 18% on (brokerage + exchange + sebi)
    assert c.gst == pytest.approx(0.18 * (0.297 + 0.01), abs=1e-3)
    # No DP on buy
    assert c.dp_charge == 0.0
    # Slippage high liquidity = max(0.05, 0.05% * trade_value) = max(0.05, 5.0) = 5.0
    assert c.slippage == pytest.approx(5.0)


def test_trade_cost_sell_includes_dp() -> None:
    c = compute_trade_cost(side="sell", trade_value=5_000, liquidity_bucket="high")
    assert c.dp_charge == pytest.approx(13.5)
    assert c.stamp_duty == 0.0


def test_round_trip_cost_pct_high_liquidity_rs5k() -> None:
    rt = round_trip_cost_pct(5_000.0, liquidity_bucket="high")
    # Per cost_tax_methodology.md section 4.1, round-trip is roughly 0.59% on Rs 5k high-liquidity
    assert 0.005 < rt < 0.010


def test_half_spread_buckets() -> None:
    assert half_spread_per_side(10_000, "high") == pytest.approx(5.0)
    assert half_spread_per_side(10_000, "mid") == pytest.approx(10.0)
    assert half_spread_per_side(10_000, "low") == pytest.approx(25.0)


# Tax model ----


def test_fiscal_year_indian_convention() -> None:
    assert fiscal_year_of(date(2024, 3, 31)) == 2023
    assert fiscal_year_of(date(2024, 4, 1)) == 2024
    assert fiscal_year_of(date(2024, 12, 15)) == 2024
    assert fiscal_year_of(date(2025, 3, 31)) == 2024


def test_regime_windows() -> None:
    assert regime_window(date(2017, 12, 31)) == "pre_2018"
    assert regime_window(date(2018, 4, 1)) == "2018_to_2024"
    assert regime_window(date(2024, 7, 22)) == "2018_to_2024"
    assert regime_window(date(2024, 7, 23)) == "post_2024"


def test_stcg_ltcg_rates_by_date() -> None:
    assert stcg_rate(date(2024, 7, 22)) == 0.15
    assert stcg_rate(date(2024, 7, 23)) == 0.20
    assert ltcg_rate(date(2017, 1, 1)) == 0.0
    assert ltcg_rate(date(2018, 4, 1)) == 0.10
    assert ltcg_rate(date(2024, 7, 23)) == 0.125


def test_ltcg_exemption_thresholds() -> None:
    assert ltcg_exemption(date(2024, 7, 22)) == 100_000.0
    assert ltcg_exemption(date(2024, 7, 23)) == 125_000.0


def test_compute_tax_stcg_15pct() -> None:
    # Sell in 2024-06 (pre-July-23-2024) after 6 months hold
    result = compute_tax_for_lot(
        realised_gain=10_000,
        acquisition_date=date(2023, 12, 1),
        sell_date=date(2024, 6, 1),
    )
    assert result.classification == "stcg"
    assert result.tax_payable == pytest.approx(1_500.0)


def test_compute_tax_stcg_20pct_post_jul_2024() -> None:
    result = compute_tax_for_lot(
        realised_gain=10_000,
        acquisition_date=date(2024, 1, 1),
        sell_date=date(2024, 8, 15),  # post 2024-07-23
    )
    assert result.classification == "stcg"
    assert result.tax_payable == pytest.approx(2_000.0)


def test_compute_tax_ltcg_post_2024_above_exemption() -> None:
    # Hold > 1 year, sell post-2024-07-23 with 200k gain, exemption already used
    result = compute_tax_for_lot(
        realised_gain=200_000,
        acquisition_date=date(2022, 1, 1),
        sell_date=date(2024, 8, 15),
        fy_ltcg_used_so_far=125_000.0,
    )
    assert result.classification == "ltcg"
    assert result.exemption_applied == 0.0
    assert result.tax_payable == pytest.approx(200_000 * 0.125)


def test_compute_tax_ltcg_uses_per_fy_exemption() -> None:
    result = compute_tax_for_lot(
        realised_gain=200_000,
        acquisition_date=date(2022, 1, 1),
        sell_date=date(2024, 8, 15),
        fy_ltcg_used_so_far=0.0,
    )
    assert result.exemption_applied == 125_000.0
    assert result.tax_payable == pytest.approx((200_000 - 125_000) * 0.125)


# Lot ledger ----


def test_lot_ledger_fifo_consumption() -> None:
    ledger = LotLedger()
    ledger.buy(Lot(company_id=1, quantity=10, acquisition_date=date(2023, 1, 15), cost_per_share=100.0))
    ledger.buy(Lot(company_id=1, quantity=10, acquisition_date=date(2024, 6, 15), cost_per_share=120.0))

    assert ledger.quantity(1) == 20
    result = ledger.sell(
        company_id=1, quantity=15, sale_date=date(2025, 1, 15), sale_price_per_share=140.0
    )
    # FIFO: 10 from oldest lot (acq 2023-01-15) at 140-100 = 40 each = 400 LTCG;
    # 5 from second lot (acq 2024-06-15) at 140-120 = 20 each = 100 STCG
    assert result.realised_gain == pytest.approx(500.0)
    assert ledger.quantity(1) == 5


def test_lot_ledger_sell_more_than_held_raises() -> None:
    ledger = LotLedger()
    ledger.buy(Lot(company_id=1, quantity=5, acquisition_date=date(2024, 1, 1), cost_per_share=100.0))
    with pytest.raises(ValueError, match="exceeds on-hand"):
        ledger.sell(company_id=1, quantity=10, sale_date=date(2024, 6, 1), sale_price_per_share=110.0)


# Backtester end-to-end ----


def test_backtester_runs_three_months_with_synthetic_data() -> None:
    """Smoke test: 3 months, 1 active stock, simple price path."""
    decisions = [
        MonthlyDecision(
            rebalance_date=date(2024, 1, 31),
            monthly_capital=25_000,
            index_amount=15_000,
            active_allocations=((1, "TCS", 5_000, 3_500.0),),
        ),
        MonthlyDecision(
            rebalance_date=date(2024, 2, 29),
            monthly_capital=25_000,
            index_amount=15_000,
            active_allocations=((1, "TCS", 5_000, 3_600.0),),
        ),
        MonthlyDecision(
            rebalance_date=date(2024, 3, 31),
            monthly_capital=25_000,
            index_amount=15_000,
            active_allocations=((1, "TCS", 5_000, 3_700.0),),
        ),
    ]

    def price_at(company_id: int, d: date) -> float:
        # Use the last decision's price for the company
        for dec in reversed(decisions):
            if dec.rebalance_date <= d:
                for cid, _sym, _amt, p in dec.active_allocations:
                    if cid == company_id:
                        return p
        return 0.0

    def benchmark_return(d: date) -> float:
        return 0.01  # 1% per month

    points, summary = run_monthly_sip_backtest(
        decisions, price_at=price_at, benchmark_return_for_month=benchmark_return
    )
    assert len(points) == 3
    assert summary.months == 3
    assert summary.final_benchmark_nav > 0
    assert summary.cumulative_capital_deployed == 75_000
    # Active stock: 1 share each month = 3 shares total cost ~10800; final price 3700 -> 11100
    assert summary.final_gross_nav > 0
