"""Phase 15: monthly deployment report generator.

Produces the Markdown report described in scoring_methodology.md section 8
and v2 plan section 22. The report consumes the deployment plan (Phase 12),
the Portfolio Edge Score breakdown (Phase 11), and the per-candidate
Monthly Buy Score values (Phase 10/4-9). It does NOT call engines — every
input is materialised by upstream modules.
"""

from __future__ import annotations

from datetime import date
from io import StringIO

from ..engines.deployment import ActionPlan, DeploymentSplit
from ..engines.portfolio_edge import EdgeScoreBreakdown


def render_monthly_report(
    *,
    rebalance_date: date,
    split: DeploymentSplit,
    actions: list[ActionPlan],
    edge: EdgeScoreBreakdown,
    benchmark: str = "Nifty 500 TRI",
) -> str:
    """Return a Markdown report. The caller persists it to data/reports/."""
    out = StringIO()
    out.write(f"# Monthly Rs {split.monthly_capital:,} Deployment Plan\n\n")
    out.write(f"Month: {rebalance_date.isoformat()}\n")
    out.write(f"Capital available: Rs {split.monthly_capital:,}\n")
    out.write(f"Benchmark: {benchmark}\n")
    out.write(f"Portfolio Edge Score: {edge.pes}\n")
    out.write(f"Active allocation: Rs {split.active_amount:,}\n")
    out.write(f"Index allocation: Rs {split.index_amount:,}\n\n")

    out.write("## Final Deployment\n\n")
    if not actions:
        out.write("(no actions)\n\n")
    else:
        for i, a in enumerate(actions, start=1):
            target = a.symbol or "INDEX"
            out.write(
                f"{i}. **{a.action_type}** {target} | "
                f"target Rs {a.target_amount:,} | qty {a.executable_quantity} | "
                f"trade Rs {a.estimated_trade_value:,.0f} | "
                f"residual Rs {a.residual_amount:,} -> {a.residual_destination} | "
                f"{a.reason}\n"
            )
        out.write("\n")

    out.write("## Why Not Just Buy Index?\n\n")
    if split.active_amount == 0:
        out.write(
            f"All Rs {split.monthly_capital:,} went to the index leg because the Portfolio Edge Score "
            f"was {edge.pes} (bucket <= 50). No active stock cleared the strong-candidate "
            "threshold this month.\n\n"
        )
    else:
        out.write(
            f"PES {edge.pes} put Rs {split.active_amount:,} into active stocks. See per-candidate evidence "
            "and cohort backing alongside each action above.\n\n"
        )

    out.write("## Portfolio Edge Score Breakdown\n\n")
    out.write(f"- Active Opportunity Breadth: {edge.active_opportunity_breadth}\n")
    out.write(f"- Top Candidate Quality: {edge.top_candidate_quality}\n")
    out.write(f"- Evidence Quality (top N): {edge.evidence_quality_topn}\n")
    out.write(f"- Market Regime Support: {edge.market_regime_support}\n")
    out.write(f"- Existing Portfolio Add Opportunity: {edge.existing_portfolio_add_opportunity}\n")
    out.write(f"- Risk/Cost Penalty: {edge.risk_cost_penalty}\n")
    out.write(f"- **Portfolio Edge Score: {edge.pes}**\n\n")

    return out.getvalue()
