"""Load the delisted-companies seed list (Phase 2.5).

Expected CSV columns:
  symbol, company_name, isin, exchange, sector, industry,
  market_cap_category, listing_date, delisting_date, event_type,
  recovery_rate, source_url, notes

Behaviour:
- Inserts or updates Company with status='delisted' and the
  supplied delisting_date.
- Inserts a DelistingEvent row referencing the company with the
  event_type and recovery_rate (default 0.0 per data_sources.md
  section 6 conservative rule).

This is the seed for the survivorship-correct universe required by
backtest_validity_methodology.md section 3.1 (>= 50 distressed seeds
before any strategy promotion).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import Company, DelistingEvent
from ._helpers import (
    IngestStats,
    parse_date,
    parse_date_or_none,
    parse_float_or_none,
    read_csv_dicts,
)
from .source_registry import finalize_source, hash_file, register_source

VALID_EVENT_TYPES = {
    "NCLT",
    "IBC",
    "voluntary",
    "regulatory_delisting",
    "suspension",
    "recapitalisation",
}


def load_delisted_seed_list(
    session: Session, csv_path: Path, *, source_url: str | None = None
) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="delisted_seed_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
        notes="Phase 2.5 delisted-companies seed list per data_sources.md section 6",
    )

    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        exchange = (row.get("exchange") or "NSE").strip() or "NSE"
        event_type = row["event_type"].strip()
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"unknown delisting event_type {event_type!r} for {symbol!r}; "
                f"allowed: {sorted(VALID_EVENT_TYPES)}"
            )
        event_date = parse_date(row["delisting_date"])
        recovery_rate = parse_float_or_none(row.get("recovery_rate"))
        if recovery_rate is None:
            recovery_rate = 0.0

        existing = session.execute(
            select(Company).where(Company.symbol == symbol, Company.exchange == exchange)
        ).scalar_one_or_none()
        if existing is None:
            company = Company(
                symbol=symbol,
                company_name=row["company_name"].strip(),
                isin=(row.get("isin") or "").strip() or None,
                exchange=exchange,
                sector=(row.get("sector") or "").strip() or None,
                industry=(row.get("industry") or "").strip() or None,
                market_cap_category=(row.get("market_cap_category") or "").strip() or None,
                listing_date=parse_date_or_none(row.get("listing_date")),
                delisting_date=event_date,
                status="delisted",
                source_id=src.id,
            )
            session.add(company)
            session.flush()
            stats.rows_added += 1
        else:
            existing.delisting_date = event_date
            existing.status = "delisted"
            stats.rows_updated += 1
            company = existing

        session.add(
            DelistingEvent(
                company_id=company.id,
                event_date=event_date,
                event_type=event_type,
                recovery_rate=recovery_rate,
                source_url=(row.get("source_url") or "").strip() or None,
                notes=(row.get("notes") or "").strip() or None,
                source_id=src.id,
            )
        )

    finalize_source(
        session,
        src,
        rows_added=stats.rows_added,
        rows_updated=stats.rows_updated,
    )
    return stats
