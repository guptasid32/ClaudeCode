"""Load daily prices.

Expected CSV columns:
  symbol, trade_date, open, high, low, close, volume,
  delivery_volume, delivery_percentage, turnover

trade_date is the source_timestamp per point_in_time_methodology.md
section 1: the close of trade_date T is available end-of-day T.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import PriceDaily
from ._helpers import (
    IngestStats,
    lookup_company_id,
    parse_date,
    parse_float_or_none,
    parse_int_or_none,
    read_csv_dicts,
)
from .source_registry import finalize_source, hash_file, register_source


def load_prices(session: Session, csv_path: Path, *, source_url: str | None = None) -> IngestStats:
    stats = IngestStats()
    src = register_source(
        session,
        source_type="prices_csv",
        source_url=source_url,
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )

    for row in read_csv_dicts(csv_path):
        symbol = row["symbol"].strip()
        company_id = lookup_company_id(session, symbol, row.get("exchange", "NSE").strip() or "NSE")
        trade_date = parse_date(row["trade_date"])
        existing = session.execute(
            select(PriceDaily).where(
                PriceDaily.company_id == company_id, PriceDaily.trade_date == trade_date
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                PriceDaily(
                    company_id=company_id,
                    trade_date=trade_date,
                    open=parse_float_or_none(row.get("open")),
                    high=parse_float_or_none(row.get("high")),
                    low=parse_float_or_none(row.get("low")),
                    close=float(row["close"]),
                    adjusted_close=parse_float_or_none(row.get("adjusted_close"))
                    if row.get("adjusted_close")
                    else float(row["close"]),
                    volume=parse_int_or_none(row.get("volume")),
                    delivery_volume=parse_int_or_none(row.get("delivery_volume")),
                    delivery_percentage=parse_float_or_none(row.get("delivery_percentage")),
                    turnover=parse_float_or_none(row.get("turnover")),
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
