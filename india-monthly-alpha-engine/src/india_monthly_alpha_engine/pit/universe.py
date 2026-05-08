"""PIT universe queries (Phase 2.5 foundation; full PIT loader arrives Phase 3).

This module provides the survivorship-correct universe queries that
backtest_validity_methodology.md section 3 requires:

  universe(t) = get_companies_active_at(t) U get_delisted_companies_active_at(t)

Per architecture.md section 5, only `pit/` is permitted to read raw history
models. These helpers are the seed of the canonical PIT loader interface
specified in point_in_time_methodology.md section 3.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db.models_raw import Company


def get_companies_active_at(session: Session, as_of_date: date) -> set[int]:
    """Currently-active companies that were trading at as_of_date.

    Returns only companies with NO delisting_date (i.e., still listed today).
    The survivorship-correction subset (companies that were trading at
    as_of_date but have since been delisted) is provided by
    `get_delisted_companies_active_at`. The full universe is their union.
    """
    stmt = select(Company.id).where(
        or_(Company.listing_date.is_(None), Company.listing_date <= as_of_date),
        Company.delisting_date.is_(None),
    )
    return set(session.execute(stmt).scalars().all())


def get_delisted_companies_active_at(session: Session, as_of_date: date) -> set[int]:
    """Companies that were trading at as_of_date but have since been delisted.

    A company is in this set if listing_date <= as_of_date < delisting_date.
    These are the survivorship-correction companies the backtest must
    include in its universe (backtest_validity_methodology.md section 3).
    """
    stmt = select(Company.id).where(
        Company.delisting_date.is_not(None),
        or_(Company.listing_date.is_(None), Company.listing_date <= as_of_date),
        Company.delisting_date > as_of_date,
    )
    return set(session.execute(stmt).scalars().all())


def get_universe_at(session: Session, as_of_date: date) -> set[int]:
    """Survivorship-correct universe at as_of_date.

    Per backtest_validity_methodology.md section 3:

        universe(t) = get_companies_active_at(t) U get_delisted_companies_active_at(t)

    This function is the canonical entry point for backtest universe
    construction. It does NOT filter by index membership — that is a
    separate intersection done by the caller, via
    get_index_constituents_as_of (Phase 3 PIT loader).
    """
    return get_companies_active_at(session, as_of_date) | get_delisted_companies_active_at(
        session, as_of_date
    )
