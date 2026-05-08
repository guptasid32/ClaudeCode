"""Date-aware tax regime per cost_tax_methodology.md section 5.

Three windows keyed off the realisation (sell) date:
- Pre-2018-04-01: STCG 15%, LTCG 0% (listed equity exempt under 10(38)).
- 2018-04-01 to 2024-07-23: STCG 15%, LTCG 10% above Rs 1,00,000 per FY.
- Post-2024-07-23: STCG 20%, LTCG 12.5% above Rs 1,25,000 per FY.

Surcharge and cess are intentionally not modelled in v1; the omission
is documented as a small approximation for users in higher slabs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

CUTOFF_2018 = date(2018, 4, 1)
CUTOFF_2024 = date(2024, 7, 23)


@dataclass(frozen=True)
class TaxComputation:
    realised_gain: float
    holding_period_days: int
    classification: str  # "stcg" | "ltcg"
    rate_pct: float  # decimal
    exemption_applied: float
    tax_payable: float


def fiscal_year_of(d: date) -> int:
    """Indian FY: 1 April to 31 March. Returns the start year of the FY containing d."""
    return d.year if d.month >= 4 else d.year - 1


def regime_window(sell_date: date) -> str:
    if sell_date < CUTOFF_2018:
        return "pre_2018"
    if sell_date < CUTOFF_2024:
        return "2018_to_2024"
    return "post_2024"


def stcg_rate(sell_date: date) -> float:
    if sell_date < CUTOFF_2024:
        return 0.15
    return 0.20


def ltcg_rate(sell_date: date) -> float:
    if sell_date < CUTOFF_2018:
        return 0.0
    if sell_date < CUTOFF_2024:
        return 0.10
    return 0.125


def ltcg_exemption(sell_date: date) -> float:
    if sell_date < CUTOFF_2018:
        return 0.0
    if sell_date < CUTOFF_2024:
        return 100_000.0
    return 125_000.0


def compute_tax_for_lot(
    *,
    realised_gain: float,
    acquisition_date: date,
    sell_date: date,
    fy_ltcg_used_so_far: float = 0.0,
) -> TaxComputation:
    """Tax on a single lot consumption.

    fy_ltcg_used_so_far is the cumulative realised LTCG (gross of tax)
    already booked in the FY of `sell_date`. The simulator passes this
    in so the per-FY exemption is correctly tracked across multiple
    sells. Exemption applies only to the LTCG component.
    """
    days = (sell_date - acquisition_date).days
    if days < 365:
        rate = stcg_rate(sell_date)
        tax = max(0.0, realised_gain) * rate
        return TaxComputation(
            realised_gain=realised_gain,
            holding_period_days=days,
            classification="stcg",
            rate_pct=rate,
            exemption_applied=0.0,
            tax_payable=tax,
        )

    rate = ltcg_rate(sell_date)
    exemption_total = ltcg_exemption(sell_date)
    exemption_left = max(0.0, exemption_total - fy_ltcg_used_so_far)
    if realised_gain <= 0:
        return TaxComputation(
            realised_gain=realised_gain,
            holding_period_days=days,
            classification="ltcg",
            rate_pct=rate,
            exemption_applied=0.0,
            tax_payable=0.0,
        )
    exemption_applied = min(exemption_left, realised_gain)
    taxable = realised_gain - exemption_applied
    tax = taxable * rate
    return TaxComputation(
        realised_gain=realised_gain,
        holding_period_days=days,
        classification="ltcg",
        rate_pct=rate,
        exemption_applied=exemption_applied,
        tax_payable=tax,
    )
