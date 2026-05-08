"""Phase 4: corporate-action-adjusted prices.

Derives `adjusted_close` from a price series and the corporate actions
applicable to that company. Per backtest_validity_methodology.md
section 4.1, splits, bonuses, and dividends adjust prices backward from
their ex_date; rights, buybacks, mergers, demergers, and delistings
require explicit per-event handling and otherwise raise so the
backtest fails loudly rather than silently mis-pricing.

Convention for ratio fields (data_sources.md): ratio_numerator counts
OLD shares, ratio_denominator counts NEW shares.
- split 1:2 (one old share becomes two new) -> numerator=1, denominator=2,
  factor = 1/2 = 0.5; pre-split price is halved.
- bonus 1:1 (one bonus per one old) -> numerator=1, denominator=1,
  factor = denominator / (numerator + denominator) = 1/2 = 0.5.
"""

from __future__ import annotations

from dataclasses import replace

from ..pit.point_in_time_loader import CorporateActionRow, PriceRow


def _adjustment_factor(action: CorporateActionRow, prev_close: float) -> float:
    """Backward-multiply factor applied to closes BEFORE the ex_date."""
    a = action.action_type
    if a == "split":
        if action.ratio_numerator is None or action.ratio_denominator is None:
            raise ValueError("split corporate action missing ratio")
        return action.ratio_numerator / action.ratio_denominator
    if a == "bonus":
        if action.ratio_numerator is None or action.ratio_denominator is None:
            raise ValueError("bonus corporate action missing ratio")
        return action.ratio_denominator / (action.ratio_numerator + action.ratio_denominator)
    if a == "dividend":
        cash = action.cash_amount or 0.0
        if cash <= 0 or prev_close <= 0:
            return 1.0
        return (prev_close - cash) / prev_close
    if a in {"rights", "buyback", "merger", "demerger", "delisting"}:
        raise NotImplementedError(
            f"corporate action type {a!r} requires per-event handling and is not "
            "supported by the simple adjusted-close pipeline. The backtester must "
            "tag positions affected by this action as unsupported or implement "
            "the per-event treatment in backtest_validity_methodology.md section 4.1."
        )
    raise ValueError(f"unknown corporate action type {a!r}")


def compute_adjusted_close(
    prices: list[PriceRow], corporate_actions: list[CorporateActionRow]
) -> list[PriceRow]:
    """Return the price series with adjusted_close set per the corporate actions.

    Continuity rule: a holding's pre-ex price multiplied by the adjustment
    factor should equal the post-ex price (modulo dividend cash flow). Tested
    by backtest_validity_methodology.md section 10.6.
    """
    if not prices:
        return []

    sorted_prices = sorted(prices, key=lambda p: p.trade_date)
    # Iterate ALL corporate actions; unsupported types raise via _adjustment_factor.
    actions = sorted(corporate_actions, key=lambda a: a.ex_date)

    raw_closes = [p.close for p in sorted_prices]
    adjusted = list(raw_closes)

    # Walk corporate actions in chronological order; each action multiplies
    # the adjusted close of every price strictly BEFORE its ex_date.
    for action in actions:
        # For dividend factor we use the close on the trading day immediately
        # before ex_date.
        idx_before_ex = -1
        for i, p in enumerate(sorted_prices):
            if p.trade_date < action.ex_date:
                idx_before_ex = i
            else:
                break
        if idx_before_ex < 0:
            # Action precedes our price history; nothing to adjust backward.
            continue
        prev_close = adjusted[idx_before_ex]
        factor = _adjustment_factor(action, prev_close)
        for i in range(idx_before_ex + 1):
            adjusted[i] = adjusted[i] * factor

    return [replace(p, adjusted_close=adjusted[i]) for i, p in enumerate(sorted_prices)]


def total_return(prices: list[PriceRow]) -> float:
    """Total return computed from the first to last adjusted close.

    Returns 0.0 for an empty or single-row series.
    """
    if len(prices) < 2:
        return 0.0
    sorted_prices = sorted(prices, key=lambda p: p.trade_date)
    first = sorted_prices[0].adjusted_close or sorted_prices[0].close
    last = sorted_prices[-1].adjusted_close or sorted_prices[-1].close
    if first <= 0:
        return 0.0
    return (last / first) - 1.0
