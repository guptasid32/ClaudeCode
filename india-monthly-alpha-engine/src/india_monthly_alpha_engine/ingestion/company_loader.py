"""Load the companies master table.

Expected CSV columns (header row):
  symbol, company_name, isin, exchange, sector, industry,
  market_cap_category, listing_date, status

Every other loader looks up company_id by (symbol, exchange), so this
must be loaded first.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import Company
from ._helpers import IngestStats, parse_date_or_none, read_csv_dicts
from .source_registry import finalize_source, hash_file, register_source


def load_companies(session: Session, csv_path: Path, *, source_url: str | None = None) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="companies_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )

    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        exchange = row.get("exchange", "NSE").strip() or "NSE"
        existing = session.execute(
            select(Company).where(Company.symbol == symbol, Company.exchange == exchange)
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Company(
                    symbol=symbol,
                    company_name=row["company_name"].strip(),
                    isin=(row.get("isin") or "").strip() or None,
                    exchange=exchange,
                    sector=(row.get("sector") or "").strip() or None,
                    industry=(row.get("industry") or "").strip() or None,
                    market_cap_category=(row.get("market_cap_category") or "").strip() or None,
                    listing_date=parse_date_or_none(row.get("listing_date")),
                    status=(row.get("status") or "active").strip() or "active",
                    source_id=src.id,
                )
            )
            stats.rows_added += 1
        else:
            existing.company_name = row["company_name"].strip()
            existing.sector = (row.get("sector") or existing.sector or "").strip() or existing.sector
            existing.industry = (row.get("industry") or existing.industry or "").strip() or existing.industry
            existing.market_cap_category = (
                (row.get("market_cap_category") or "").strip() or existing.market_cap_category
            )
            existing.status = (row.get("status") or existing.status).strip() or existing.status
            stats.rows_updated += 1

    finalize_source(
        session,
        src,
        rows_added=stats.rows_added,
        rows_updated=stats.rows_updated,
    )
    return stats
