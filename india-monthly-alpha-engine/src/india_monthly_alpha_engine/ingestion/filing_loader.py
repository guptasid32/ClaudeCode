"""Load filings metadata.

Expected CSV columns:
  symbol, filing_type, title, filing_date, exchange, source_url,
  local_path, document_hash, parser_version, source_tier

filing_date is the source_timestamp per point_in_time_methodology.md
section 1.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import Filing
from ._helpers import IngestStats, lookup_company_id, parse_date, parse_int_or_none, read_csv_dicts
from .source_registry import finalize_source, hash_file, register_source


def load_filings(session: Session, csv_path: Path, *, source_url: str | None = None) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="filings_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )

    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol)
        filing_date = parse_date(row["filing_date"])
        document_hash = (row.get("document_hash") or "").strip() or None

        existing = None
        if document_hash:
            existing = session.execute(
                select(Filing).where(
                    Filing.company_id == company_id,
                    Filing.document_hash == document_hash,
                )
            ).scalar_one_or_none()

        if existing is None:
            session.add(
                Filing(
                    company_id=company_id,
                    filing_type=row["filing_type"].strip(),
                    title=row["title"].strip(),
                    filing_date=filing_date,
                    exchange=(row.get("exchange") or "NSE").strip() or "NSE",
                    source_url=(row.get("source_url") or "").strip() or None,
                    local_path=(row.get("local_path") or "").strip() or None,
                    raw_text_path=(row.get("raw_text_path") or "").strip() or None,
                    document_hash=document_hash,
                    parser_version=(row.get("parser_version") or "v0").strip() or "v0",
                    source_tier=parse_int_or_none(row.get("source_tier")) or 1,
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
