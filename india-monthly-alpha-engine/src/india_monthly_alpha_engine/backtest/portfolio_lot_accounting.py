"""FIFO portfolio-lot accounting per cost_tax_methodology.md section 6.

A simulator-level abstraction over `portfolio_lots`. The DB representation
in db/models.py is the persisted form; this module provides the in-memory
ledger the backtester operates on for replay determinism.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import date

from .tax_model import TaxComputation, compute_tax_for_lot, fiscal_year_of


@dataclass(frozen=True)
class Lot:
    company_id: int
    quantity: int
    acquisition_date: date
    cost_per_share: float


@dataclass(frozen=True)
class SellResult:
    company_id: int
    quantity_sold: int
    sale_date: date
    sale_price_per_share: float
    realised_gain: float
    tax: TaxComputation
    lots_consumed: tuple[tuple[Lot, int], ...]  # (lot, qty consumed)


class LotLedger:
    """FIFO lot store + per-FY LTCG exemption tracker."""

    def __init__(self) -> None:
        self._lots: dict[int, deque[Lot]] = defaultdict(deque)
        self._fy_ltcg_realised: dict[int, float] = defaultdict(float)

    def buy(self, lot: Lot) -> None:
        self._lots[lot.company_id].append(lot)

    def quantity(self, company_id: int) -> int:
        return sum(lot.quantity for lot in self._lots[company_id])

    def sell(
        self,
        *,
        company_id: int,
        quantity: int,
        sale_date: date,
        sale_price_per_share: float,
    ) -> SellResult:
        """Consume `quantity` from the FIFO queue. Splits the head lot if needed."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        on_hand = self.quantity(company_id)
        if quantity > on_hand:
            raise ValueError(
                f"sell quantity {quantity} exceeds on-hand {on_hand} for company {company_id}"
            )

        consumed: list[tuple[Lot, int]] = []
        remaining = quantity
        realised_gain_total = 0.0
        tax_total = 0.0
        # We compute tax per-lot but keep the LTCG exemption running across lots.
        fy = fiscal_year_of(sale_date)
        running_fy_ltcg_used = self._fy_ltcg_realised[fy]
        # Stitch a single TaxComputation for the aggregate sell; the per-lot
        # detail is preserved in `consumed` for audit.
        first_classification = ""
        first_rate = 0.0
        ltcg_exemption_applied = 0.0
        first_holding_days = 0

        while remaining > 0:
            head = self._lots[company_id][0]
            take = min(head.quantity, remaining)
            realised = (sale_price_per_share - head.cost_per_share) * take
            tax_calc = compute_tax_for_lot(
                realised_gain=realised,
                acquisition_date=head.acquisition_date,
                sell_date=sale_date,
                fy_ltcg_used_so_far=running_fy_ltcg_used,
            )
            realised_gain_total += realised
            tax_total += tax_calc.tax_payable
            ltcg_exemption_applied += tax_calc.exemption_applied
            if tax_calc.classification == "ltcg" and realised > 0:
                running_fy_ltcg_used += realised - tax_calc.exemption_applied + tax_calc.exemption_applied
                # i.e. the gross gain counts toward the exemption-tracker; exemption already
                # consumed within this lot.
            first_classification = first_classification or tax_calc.classification
            first_rate = first_rate or tax_calc.rate_pct
            first_holding_days = first_holding_days or tax_calc.holding_period_days

            consumed.append((head, take))

            if take == head.quantity:
                self._lots[company_id].popleft()
            else:
                self._lots[company_id][0] = replace(head, quantity=head.quantity - take)
            remaining -= take

        # Persist the running LTCG counter
        self._fy_ltcg_realised[fy] = running_fy_ltcg_used

        aggregate_tax = TaxComputation(
            realised_gain=realised_gain_total,
            holding_period_days=first_holding_days,
            classification=first_classification or "stcg",
            rate_pct=first_rate,
            exemption_applied=ltcg_exemption_applied,
            tax_payable=tax_total,
        )

        return SellResult(
            company_id=company_id,
            quantity_sold=quantity,
            sale_date=sale_date,
            sale_price_per_share=sale_price_per_share,
            realised_gain=realised_gain_total,
            tax=aggregate_tax,
            lots_consumed=tuple(consumed),
        )
