"""Load historical index constituents.

Expected CSV columns:
  index_name, symbol, effective_from, effective_to, weight

`effective_from` is the source_timestamp per point_in_time_methodology.md
section 1: the operational change date, not the announcement date.
NSE rebalances Nifty 500 semi-annually.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import IndexConstituentHistory
from ._helpers import (
    IngestStats,
    lookup_company_id,
    parse_date,
    parse_date_or_none,
    parse_float_or_none,
    read_csv_dicts,
)
from .source_registry import finalize_source, hash_file, register_source


def load_index_constituents(
    session: Session, csv_path: Path, *, source_url: str | None = None
) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="index_constituents_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )

    for row in read_csv_dicts(csv_path):
        index_name = row["index_name"].strip()
        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol)
        effective_from = parse_date(row["effective_from"])

        existing = session.execute(
            select(IndexConstituentHistory).where(
                IndexConstituentHistory.index_name == index_name,
                IndexConstituentHistory.company_id == company_id,
                IndexConstituentHistory.effective_from == effective_from,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                IndexConstituentHistory(
                    index_name=index_name,
                    company_id=company_id,
                    symbol=symbol,
                    effective_from=effective_from,
                    effective_to=parse_date_or_none(row.get("effective_to")),
                    weight=parse_float_or_none(row.get("weight")),
                    source_id=src.id,
                )
            )
            stats.rows_added += 1
        else:
            existing.effective_to = parse_date_or_none(row.get("effective_to")) or existing.effective_to
            existing.weight = parse_float_or_none(row.get("weight")) or existing.weight
            stats.rows_updated += 1

    finalize_source(
        session,
        src,
        rows_added=stats.rows_added,
        rows_updated=stats.rows_updated,
    )
    return stats
