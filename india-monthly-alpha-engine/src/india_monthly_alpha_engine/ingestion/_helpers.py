"""Internal helpers shared across loaders."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models_raw import Company


def read_csv_dicts(path: Path) -> Iterator[dict[str, str]]:
    """Yield dict rows from a CSV with header row. Empty cells become empty strings."""
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        yield from reader


def parse_date(s: str) -> date:
    """Parse YYYY-MM-DD; raise ValueError on bad input."""
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def parse_date_or_none(s: str | None) -> date | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return parse_date(s)


def parse_float_or_none(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return float(s)


def parse_int_or_none(s: str | None) -> int | None:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return int(s)


def lookup_company_id(session: Session, symbol: str, exchange: str = "NSE") -> int:
    """Return company_id by (symbol, exchange). Raises if missing."""
    stmt = select(Company).where(Company.symbol == symbol, Company.exchange == exchange)
    result = session.execute(stmt).scalar_one_or_none()
    if result is None:
        raise LookupError(f"company not found: {symbol!r} on {exchange!r}")
    return result.id


class IngestStats:
    __slots__ = ("rows_added", "rows_updated", "rows_skipped")

    def __init__(self) -> None:
        self.rows_added = 0
        self.rows_updated = 0
        self.rows_skipped = 0

    def __repr__(self) -> str:
        return (
            f"IngestStats(added={self.rows_added}, "
            f"updated={self.rows_updated}, skipped={self.rows_skipped})"
        )
