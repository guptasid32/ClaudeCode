"""Cost model per cost_tax_methodology.md sections 2-3.

Direct equity, delivery, long-only, post-2023 rates with the
zero_delivery brokerage default. Component breakdown is exposed so
the cost-drag test (backtest_validity_methodology.md section 10.3)
can verify it against an analytical estimate within +/- 20% relative.
"""

from __future__ import annotations

from dataclasses import dataclass

# Components (post-2023)
STT_DELIVERY_PCT = 0.0010  # 0.10% per side
STAMP_DUTY_BUY_PCT = 0.00015
NSE_EXCHANGE_PCT = 0.0000297
SEBI_FEE_PCT = 0.000001
GST_RATE = 0.18
DP_CHARGE_FLAT = 13.5  # CDSL


@dataclass(frozen=True)
class TradeCost:
    stt: float
    stamp_duty: float
    exchange: float
    sebi: float
    gst: float
    brokerage: float
    dp_charge: float
    slippage: float
    total: float


def half_spread_per_side(trade_value: float, liquidity_bucket: str) -> float:
    if liquidity_bucket == "high":
        per_side = max(0.05, 0.0005 * trade_value)
    elif liquidity_bucket == "mid":
        per_side = max(0.10, 0.0010 * trade_value)
    else:  # low
        per_side = max(0.25, 0.0025 * trade_value)
    return per_side


def compute_trade_cost(
    *,
    side: str,  # "buy" | "sell"
    trade_value: float,
    liquidity_bucket: str = "high",
    brokerage_model: str = "zero_delivery",
) -> TradeCost:
    """Cost for a single trade leg."""
    stt = trade_value * STT_DELIVERY_PCT
    stamp = trade_value * STAMP_DUTY_BUY_PCT if side == "buy" else 0.0
    exchange = trade_value * NSE_EXCHANGE_PCT
    sebi = trade_value * SEBI_FEE_PCT

    if brokerage_model == "zero_delivery":
        brokerage = 0.0
    elif brokerage_model == "discount_capped":
        brokerage = min(20.0, trade_value * 0.0003)
    else:
        raise ValueError(f"unknown brokerage_model {brokerage_model!r}")

    gst = GST_RATE * (brokerage + exchange + sebi)
    dp = DP_CHARGE_FLAT if side == "sell" else 0.0
    slippage = half_spread_per_side(trade_value, liquidity_bucket)

    total = stt + stamp + exchange + sebi + gst + brokerage + dp + slippage
    return TradeCost(
        stt=stt,
        stamp_duty=stamp,
        exchange=exchange,
        sebi=sebi,
        gst=gst,
        brokerage=brokerage,
        dp_charge=dp,
        slippage=slippage,
        total=total,
    )


def round_trip_cost_pct(
    trade_value: float,
    liquidity_bucket: str = "high",
    brokerage_model: str = "zero_delivery",
) -> float:
    buy = compute_trade_cost(
        side="buy",
        trade_value=trade_value,
        liquidity_bucket=liquidity_bucket,
        brokerage_model=brokerage_model,
    )
    sell = compute_trade_cost(
        side="sell",
        trade_value=trade_value,
        liquidity_bucket=liquidity_bucket,
        brokerage_model=brokerage_model,
    )
    if trade_value <= 0:
        return 0.0
    return (buy.total + sell.total) / trade_value
