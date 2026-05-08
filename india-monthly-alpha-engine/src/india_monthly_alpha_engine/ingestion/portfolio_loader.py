"""Load the user's current portfolio.

Two CSV inputs are supported:

Holdings CSV columns:
  symbol, quantity, average_price, sector, entry_date, thesis_status

Lots CSV columns:
  symbol, quantity, acquisition_date, cost_per_share, total_cost,
  pre_grandfather_fmv

Holdings is the aggregate-level snapshot; lots is the FIFO tax-lot
ledger required by cost_tax_methodology.md section 6 for STCG/LTCG
classification on every sell.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ..db.models import PortfolioHolding, PortfolioLot
from ._helpers import (
    IngestStats,
    lookup_company_id,
    parse_date,
    parse_date_or_none,
    parse_float_or_none,
    read_csv_dicts,
)


def load_portfolio_holdings(session: Session, csv_path: Path) -> IngestStats:
    stats = IngestStats()
    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol)
        session.add(
            PortfolioHolding(
                company_id=company_id,
                symbol=symbol,
                quantity=int(row["quantity"]),
                average_price=float(row["average_price"]),
                sector=(row.get("sector") or "").strip() or None,
                entry_date=parse_date_or_none(row.get("entry_date")),
                thesis_status=(row.get("thesis_status") or "intact").strip() or "intact",
            )
        )
        stats.rows_added += 1
    return stats


def load_portfolio_lots(session: Session, csv_path: Path) -> IngestStats:
    stats = IngestStats()
    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol)
        quantity = int(row["quantity"])
        cost_per_share = float(row["cost_per_share"])
        total_cost = parse_float_or_none(row.get("total_cost"))
        if total_cost is None:
            total_cost = cost_per_share * quantity
        session.add(
            PortfolioLot(
                company_id=company_id,
                symbol=symbol,
                quantity=quantity,
                acquisition_date=parse_date(row["acquisition_date"]),
                cost_per_share=cost_per_share,
                total_cost=total_cost,
                pre_grandfather_fmv=parse_float_or_none(row.get("pre_grandfather_fmv")),
            )
        )
        stats.rows_added += 1
    return stats
