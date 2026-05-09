"""End-to-end real-data backtest runner.

Walks rebalance dates between --start and --end, calls the orchestrator
each month to produce a deployment plan, then feeds the resulting actions
into the monthly SIP backtester to produce the equity curve, drawdown,
and CAGR vs benchmark.

Usage:

    python -m india_monthly_alpha_engine.tools.run_backtest \
        --start 2014-01-01 --end 2018-12-31

Refuses to run if the requested window touches the locked holdout
(2023-01-01 to 2024-12-31) without an explicit --allow-holdout flag,
which itself REQUIRES --pre-registered-strategy=<name> to enforce
the single-shot promotion rule from
backtest_validity_methodology.md section 7.4.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import get_settings
from ..app.logging_config import configure_logging, get_logger
from ..backtest.monthly_sip_backtester import MonthlyDecision, run_monthly_sip_backtest
from ..db.models import BenchmarkPrice, MonthlyBuyAction
from ..db.session import get_session
from ..engines.orchestrator import run_monthly_cycle
from ..pit.point_in_time_loader import get_prices_until

HOLDOUT_START = date(2023, 1, 1)


def _month_ends(start: date, end: date) -> list[date]:
    """Return the last business day of each month in [start, end]."""
    out: list[date] = []
    cur = start.replace(day=1)
    while cur <= end:
        # Move to the first of next month, then back one day -> month-end
        if cur.month == 12:
            next_month = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            next_month = cur.replace(month=cur.month + 1, day=1)
        last = next_month - timedelta(days=1)
        # Roll back to weekday
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        if start <= last <= end:
            out.append(last)
        cur = next_month
    return out


def _benchmark_close(session: Session, index_name: str, on_or_before: date) -> float | None:
    stmt = (
        select(BenchmarkPrice)
        .where(BenchmarkPrice.index_name == index_name, BenchmarkPrice.trade_date <= on_or_before)
        .order_by(BenchmarkPrice.trade_date.desc())
        .limit(1)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if row is None:
        return None
    return row.tri_close if row.tri_close is not None else row.close


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--capital", type=int, default=25_000)
    p.add_argument("--benchmark", type=str, default="NIFTY_500_TRI")
    p.add_argument("--universe-index", type=str, default="NIFTY_500")
    p.add_argument("--cohort-step-days", type=int, default=180)
    p.add_argument("--allow-holdout", action="store_true")
    p.add_argument("--pre-registered-strategy", type=str, default=None)
    args = p.parse_args()

    if args.end >= HOLDOUT_START and not args.allow_holdout:
        print(
            f"refusing to run past holdout boundary {HOLDOUT_START} without --allow-holdout. "
            "see backtest_validity_methodology.md section 7.4 / 7.5",
            file=sys.stderr,
        )
        return 2
    if args.allow_holdout and not args.pre_registered_strategy:
        print(
            "--allow-holdout requires --pre-registered-strategy=<name@version> to enforce the "
            "single-shot promotion rule",
            file=sys.stderr,
        )
        return 2

    settings = get_settings()
    configure_logging(settings)
    log = get_logger("backtest")

    rebalance_dates = _month_ends(args.start, args.end)
    decisions: list[MonthlyDecision] = []

    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with get_session(settings.sqlite_url) as session:
        for rb_date in rebalance_dates:
            result = run_monthly_cycle(
                session,
                as_of_date=rb_date,
                monthly_capital=args.capital,
                benchmark_index=args.benchmark,
                universe_index=args.universe_index,
                cohort_observation_step_days=args.cohort_step_days,
            )
            actions = (
                session.execute(
                    select(MonthlyBuyAction).where(MonthlyBuyAction.deployment_plan_id == result.plan_id)
                )
                .scalars()
                .all()
            )
            buys = tuple(
                (a.company_id, a.symbol or "", a.target_amount, a.estimated_trade_value / max(1, a.executable_quantity))
                for a in actions
                if a.action_type == "new_buy" and a.company_id is not None and a.executable_quantity > 0
            )
            decisions.append(
                MonthlyDecision(
                    rebalance_date=rb_date,
                    monthly_capital=args.capital,
                    index_amount=result.index_amount,
                    active_allocations=buys,
                )
            )
            log.info("backtest.month_done", rebalance=str(rb_date), pes=result.pes, n_actions=len(actions))

        # Build closures that read from this DB session
        def price_at(company_id: int, d: date) -> float:
            rows = get_prices_until(session, company_id, d)
            for r in reversed(rows):
                return r.adjusted_close if r.adjusted_close is not None else r.close
            return 0.0

        def benchmark_return_for_month(rb_date: date) -> float:
            prev = (rb_date - timedelta(days=32)).replace(day=1)
            a = _benchmark_close(session, args.benchmark, prev)
            b = _benchmark_close(session, args.benchmark, rb_date)
            if a is None or b is None or a <= 0:
                return 0.0
            return (b / a) - 1.0

        points, summary = run_monthly_sip_backtest(
            decisions,
            price_at=price_at,
            benchmark_return_for_month=benchmark_return_for_month,
        )

    print(f"months={summary.months}")
    print(f"capital_deployed={summary.cumulative_capital_deployed:.0f}")
    print(f"final_gross_nav={summary.final_gross_nav:.0f}")
    print(f"final_net_cost_nav={summary.final_net_cost_nav:.0f}")
    print(f"final_net_cost_tax_nav={summary.final_net_cost_tax_nav:.0f}")
    print(f"final_benchmark_nav={summary.final_benchmark_nav:.0f}")
    print(f"cagr_gross={summary.cagr_gross:.4f}")
    print(f"cagr_net_cost={summary.cagr_net_cost:.4f}")
    print(f"cagr_net_cost_tax={summary.cagr_net_cost_tax:.4f}")
    print(f"cagr_benchmark={summary.cagr_benchmark:.4f}")
    print(f"max_drawdown={summary.max_drawdown_net_cost_tax:.4f}")
    print(f"longest_underperf_months={summary.longest_underperf_months}")
    print(f"cumulative_costs={summary.cumulative_costs:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
