"""Load financial statements with append-only `as_known_at` semantics.

Expected CSV columns:
  symbol, period_type, fiscal_year, fiscal_quarter, period_end_date,
  announcement_date, revenue, ebitda, ebit, pat, eps, total_assets,
  total_debt, cash, net_worth, operating_cash_flow, free_cash_flow,
  capex, receivables, inventory, payables, restatement_reason

Restatement rule (point_in_time_methodology.md section 2): if a row
already exists for (company_id, period_type, period_end_date), and the
new values differ from the latest known-at row, append a new row with
`as_known_at = announcement_date` and `supersedes_id` pointing at the
prior row. If values match, the row is skipped (no-op).

For the original announcement, `as_known_at` equals `announcement_date`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import FinancialStatement
from ._helpers import (
    IngestStats,
    lookup_company_id,
    parse_date,
    parse_float_or_none,
    parse_int_or_none,
    read_csv_dicts,
)
from .source_registry import finalize_source, hash_file, register_source

_NUMERIC_FIELDS = (
    "revenue",
    "ebitda",
    "ebit",
    "pat",
    "eps",
    "total_assets",
    "total_debt",
    "cash",
    "net_worth",
    "operating_cash_flow",
    "free_cash_flow",
    "capex",
    "receivables",
    "inventory",
    "payables",
)


def _latest_row(
    session: Session, company_id: int, period_type: str, period_end_date: date
) -> FinancialStatement | None:
    stmt = (
        select(FinancialStatement)
        .where(
            FinancialStatement.company_id == company_id,
            FinancialStatement.period_type == period_type,
            FinancialStatement.period_end_date == period_end_date,
        )
        .order_by(FinancialStatement.as_known_at.desc(), FinancialStatement.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _values_differ(existing: FinancialStatement, new_values: dict[str, float | None]) -> bool:
    for field, new_value in new_values.items():
        old_value = getattr(existing, field)
        if old_value is None and new_value is None:
            continue
        if old_value is None or new_value is None:
            return True
        if abs(float(old_value) - float(new_value)) > 1e-6:
            return True
    return False


def load_financials(session: Session, csv_path: Path, *, source_url: str | None = None) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="financials_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )

    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol)
        period_type = row["period_type"].strip()
        period_end_date = parse_date(row["period_end_date"])
        announcement_date = parse_date(row["announcement_date"])
        as_known_at = announcement_date  # original announcement; restatement bumps later

        new_values = {f: parse_float_or_none(row.get(f)) for f in _NUMERIC_FIELDS}

        latest = _latest_row(session, company_id, period_type, period_end_date)

        if latest is None:
            session.add(
                FinancialStatement(
                    company_id=company_id,
                    period_type=period_type,
                    fiscal_year=int(row["fiscal_year"]),
                    fiscal_quarter=parse_int_or_none(row.get("fiscal_quarter")),
                    period_end_date=period_end_date,
                    announcement_date=announcement_date,
                    as_known_at=as_known_at,
                    supersedes_id=None,
                    restatement_reason=None,
                    source_id=src.id,
                    parser_version="v0",
                    **new_values,
                )
            )
            stats.rows_added += 1
        elif _values_differ(latest, new_values):
            session.add(
                FinancialStatement(
                    company_id=company_id,
                    period_type=period_type,
                    fiscal_year=int(row["fiscal_year"]),
                    fiscal_quarter=parse_int_or_none(row.get("fiscal_quarter")),
                    period_end_date=period_end_date,
                    announcement_date=announcement_date,
                    as_known_at=announcement_date,
                    supersedes_id=latest.id,
                    restatement_reason=(row.get("restatement_reason") or "").strip() or "values changed",
                    source_id=src.id,
                    parser_version="v0",
                    **new_values,
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
