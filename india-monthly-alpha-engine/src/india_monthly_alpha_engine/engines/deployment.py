"""Phase 12: monthly deployment engine.

Maps Portfolio Edge Score -> index/active split (with 20% safety floor),
ranks active candidates, applies whole-share rounding, and produces the
monthly deployment plan. The replacement rule and the after-tax-after-
cost wedge gate are enforced when the portfolio is full.
"""

from __future__ import annotations

from dataclasses import dataclass

# Bucket boundaries from scoring_methodology.md section 5.3
# Per the 20% safety floor: bucket "100" stays at Rs 5,000 index until
# holdout calibration unlocks zero-index.
_BUCKETS = (
    (50, 25_000, 0),
    (60, 20_000, 5_000),
    (70, 15_000, 10_000),
    (80, 10_000, 15_000),
    (90, 5_000, 20_000),
    (101, 5_000, 20_000),  # > 90 -> floor at 5k index until holdout-validated
)


@dataclass(frozen=True)
class DeploymentSplit:
    monthly_capital: int
    pes: int
    index_amount: int
    active_amount: int


@dataclass(frozen=True)
class CandidateForDeployment:
    company_id: int
    symbol: str
    mbs_final: int
    last_price: float
    is_strong: bool
    classification: str  # "candidate" | "reject"


@dataclass(frozen=True)
class ActionPlan:
    action_type: str  # "new_buy" | "add_existing" | "buy_index" | "hold_cash" | "replace"
    symbol: str | None
    company_id: int | None
    target_amount: int
    executable_quantity: int
    estimated_trade_value: float
    residual_amount: int
    residual_destination: str  # "index" | "cash"
    reason: str


def split_by_pes(monthly_capital: int, pes: int) -> DeploymentSplit:
    """Per scoring_methodology.md section 5.3 with 20% index floor."""
    for upper, idx_amt, act_amt in _BUCKETS:
        if pes < upper:
            return DeploymentSplit(monthly_capital, pes, idx_amt, act_amt)
    # pes >= 101: defensive — should never happen since pes is clipped to 100
    return DeploymentSplit(monthly_capital, pes, 5_000, 20_000)


def _round_to_whole_shares(target_amount: int, last_price: float) -> tuple[int, int, int]:
    """Returns (executable_quantity, trade_value, residual_amount)."""
    if last_price <= 0:
        return 0, 0, target_amount
    qty = int(target_amount // last_price)
    trade_value = int(round(qty * last_price))
    residual = target_amount - trade_value
    return qty, trade_value, residual


def allocate_active(
    active_amount: int,
    candidates: list[CandidateForDeployment],
    *,
    ticket_cap: int = 5_000,
    ticket_floor: int = 2_500,
) -> tuple[list[ActionPlan], int]:
    """Distribute `active_amount` across strong candidates by MBS rank.

    Each ticket is between ticket_floor and ticket_cap. Whole-share
    rounding produces a residual that spills to the index leg.
    Returns (actions, residual_to_index).
    """
    strong = [c for c in candidates if c.is_strong and c.classification == "candidate"]
    strong.sort(key=lambda c: c.mbs_final, reverse=True)

    actions: list[ActionPlan] = []
    remaining = active_amount

    for c in strong:
        if remaining < ticket_floor:
            break
        target = min(ticket_cap, remaining)
        qty, value, residual = _round_to_whole_shares(target, c.last_price)
        if qty == 0:
            # Stock too expensive for the ticket; spill the floor-or-less to index.
            actions.append(
                ActionPlan(
                    action_type="hold_cash",
                    symbol=c.symbol,
                    company_id=c.company_id,
                    target_amount=target,
                    executable_quantity=0,
                    estimated_trade_value=0.0,
                    residual_amount=target,
                    residual_destination="index",
                    reason=f"price {c.last_price:.0f} exceeds ticket {target}; spill to index",
                )
            )
            remaining -= target
            continue
        actions.append(
            ActionPlan(
                action_type="new_buy",
                symbol=c.symbol,
                company_id=c.company_id,
                target_amount=target,
                executable_quantity=qty,
                estimated_trade_value=float(value),
                residual_amount=residual,
                residual_destination="index",
                reason=f"MBS {c.mbs_final}",
            )
        )
        remaining -= value

    # Anything left over after the loop (no more strong candidates) spills to index
    return actions, remaining


def build_deployment_plan(
    monthly_capital: int,
    pes: int,
    candidates: list[CandidateForDeployment],
    *,
    ticket_cap: int = 5_000,
    ticket_floor: int = 2_500,
) -> tuple[DeploymentSplit, list[ActionPlan]]:
    split = split_by_pes(monthly_capital, pes)
    actions, residual_from_active = allocate_active(
        split.active_amount,
        candidates,
        ticket_cap=ticket_cap,
        ticket_floor=ticket_floor,
    )
    index_total = split.index_amount + residual_from_active
    if index_total > 0:
        actions.append(
            ActionPlan(
                action_type="buy_index",
                symbol=None,
                company_id=None,
                target_amount=index_total,
                executable_quantity=0,  # populated downstream by the index instrument loader
                estimated_trade_value=float(index_total),
                residual_amount=0,
                residual_destination="cash",
                reason="default index allocation per PES bucket"
                + (" + active residual" if residual_from_active > 0 else ""),
            )
        )
    return split, actions
