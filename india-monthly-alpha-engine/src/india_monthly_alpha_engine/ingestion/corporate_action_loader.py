"""Load corporate actions.

Expected CSV columns:
  symbol, ex_date, announcement_date, action_type,
  ratio_numerator, ratio_denominator, cash_amount

action_type ∈ {split, bonus, rights, dividend, buyback, merger,
demerger, delisting}. Per backtest_validity_methodology.md section 4.1
adjusted prices are computed from these rows; unsupported action types
fail the backtest, never silently mis-price.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import CorporateAction
from ._helpers import (
    IngestStats,
    lookup_company_id,
    parse_date,
    parse_date_or_none,
    parse_float_or_none,
    read_csv_dicts,
)
from .source_registry import finalize_source, hash_file, register_source

SUPPORTED_ACTIONS = {
    "split",
    "bonus",
    "rights",
    "dividend",
    "buyback",
    "merger",
    "demerger",
    "delisting",
}


def load_corporate_actions(
    session: Session, csv_path: Path, *, source_url: str | None = None
) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="corporate_actions_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )

    for row in read_csv_dicts(csv_path):
        action_type = row["action_type"].strip().lower()
        if action_type not in SUPPORTED_ACTIONS:
            raise ValueError(
                f"unsupported corporate action type {action_type!r} for {row['symbol']!r} "
                f"on {row['ex_date']!r}; supported: {sorted(SUPPORTED_ACTIONS)}"
            )

        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol)
        ex_date = parse_date(row["ex_date"])

        existing = session.execute(
            select(CorporateAction).where(
                CorporateAction.company_id == company_id,
                CorporateAction.ex_date == ex_date,
                CorporateAction.action_type == action_type,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                CorporateAction(
                    company_id=company_id,
                    ex_date=ex_date,
                    announcement_date=parse_date_or_none(row.get("announcement_date")),
                    action_type=action_type,
                    ratio_numerator=parse_float_or_none(row.get("ratio_numerator")),
                    ratio_denominator=parse_float_or_none(row.get("ratio_denominator")),
                    cash_amount=parse_float_or_none(row.get("cash_amount")),
                    source_id=src.id,
                )
            )
            stats.rows_added += 1
        else:
            stats.rows_skipped += 1

    finalize_source(
        session,
        src,
        rows_added=stats.rows_added,
        rows_updated=stats.rows_updated,
    )
    return stats
