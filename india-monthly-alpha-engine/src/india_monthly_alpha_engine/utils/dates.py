"""Date helpers.

Phase 1 placeholder. The PIT loader will use these helpers (Phase 3+) to
ensure as_of_date math is timezone- and DST-safe and never reaches for
the wall clock from inside features/, engines/, backtest/, etc.
"""

from __future__ import annotations

from datetime import UTC, date, datetime


def parse_iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def to_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()
