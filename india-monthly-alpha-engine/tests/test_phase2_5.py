"""Phase 2.5 acceptance tests: delisted seed list + survivorship-correct universe.

Acceptance gates from v2 plan section 21 Phase 2.5:
- survivor-only and survivorship-adjusted universes both available
- survivorship gap can be measured
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from india_monthly_alpha_engine.db.models_raw import Company, DelistingEvent
from india_monthly_alpha_engine.ingestion.company_loader import load_companies
from india_monthly_alpha_engine.ingestion.delisted_loader import load_delisted_seed_list
from india_monthly_alpha_engine.pit.universe import (
    get_companies_active_at,
    get_delisted_companies_active_at,
    get_universe_at,
)


def _w(p: Path, name: str, body: str) -> Path:
    f = p / name
    f.write_text(dedent(body).lstrip("\n"), encoding="utf-8")
    return f


@pytest.fixture
def survivor_only_csv(tmp_path: Path) -> Path:
    return _w(
        tmp_path,
        "survivors.csv",
        """
        symbol,company_name,isin,exchange,sector,industry,market_cap_category,listing_date,status
        TCS,Tata Consultancy Services,INE467B01029,NSE,IT,IT Services,large,2004-08-25,active
        RELIANCE,Reliance Industries,INE002A01018,NSE,energy,Refineries,large,1995-11-29,active
        INFY,Infosys,INE009A01021,NSE,IT,IT Services,large,1993-06-14,active
        """,
    )


@pytest.fixture
def delisted_csv(tmp_path: Path) -> Path:
    return _w(
        tmp_path,
        "delisted.csv",
        """
        symbol,company_name,isin,exchange,sector,industry,market_cap_category,listing_date,delisting_date,event_type,recovery_rate,source_url,notes
        DHFL,DHFL,,NSE,financials,Housing finance,mid,1985-12-31,2021-07-15,IBC,0.0,,IBC resolution
        JET,Jet Airways,,NSE,industrials,Airlines,mid,2005-12-15,2019-06-20,NCLT,0.0,,Insolvency
        VIDEOIND,Videocon Industries,,NSE,consumer_discretionary,Consumer electronics,mid,1990-01-01,2018-06-06,NCLT,0.0,,IBC
        DCHL,Deccan Chronicle Holdings,,NSE,communications,Print media,mid,2004-12-23,2016-06-30,regulatory_delisting,0.0,,
        ABGSHIP,ABG Shipyard,,NSE,industrials,Shipbuilding,mid,2007-12-28,2017-12-30,NCLT,0.0,,
        """,
    )


def test_delisted_seed_loads(session: Session, delisted_csv: Path) -> None:
    stats = load_delisted_seed_list(session, delisted_csv)
    assert stats.rows_added == 5
    delisted = session.execute(
        select(Company).where(Company.status == "delisted")
    ).scalars().all()
    assert len(delisted) == 5
    assert all(c.delisting_date is not None for c in delisted)
    events = session.execute(select(DelistingEvent)).scalars().all()
    assert len(events) == 5
    assert all(e.recovery_rate == 0.0 for e in events)


def test_delisted_seed_unknown_event_type_raises(session: Session, tmp_path: Path) -> None:
    csv = _w(
        tmp_path,
        "bad.csv",
        """
        symbol,company_name,isin,exchange,sector,industry,market_cap_category,listing_date,delisting_date,event_type,recovery_rate,source_url,notes
        FOO,Foo Co,,NSE,IT,,mid,2010-01-01,2020-01-01,unicorn,0.0,,
        """,
    )
    with pytest.raises(ValueError, match="unknown delisting event_type"):
        load_delisted_seed_list(session, csv)


def test_universe_active_at_only_includes_active(
    session: Session, survivor_only_csv: Path, delisted_csv: Path
) -> None:
    load_companies(session, survivor_only_csv)
    load_delisted_seed_list(session, delisted_csv)

    # Date long after every delisting in the fixture
    after_all = date(2024, 1, 1)
    survivors = get_companies_active_at(session, after_all)
    assert len(survivors) == 3  # TCS, RELIANCE, INFY

    delisted_at_after_all = get_delisted_companies_active_at(session, after_all)
    assert delisted_at_after_all == set()  # all delistings are in the past


def test_universe_at_intermediate_date_includes_then_active_now_delisted(
    session: Session, survivor_only_csv: Path, delisted_csv: Path
) -> None:
    load_companies(session, survivor_only_csv)
    load_delisted_seed_list(session, delisted_csv)

    # Date when DHFL, Jet, Videocon, ABGShip were trading (DCHL delisted in 2016 already)
    mid_date = date(2017, 6, 1)
    survivor_only = get_companies_active_at(session, mid_date)
    full = get_universe_at(session, mid_date)

    delisted_active = get_delisted_companies_active_at(session, mid_date)

    assert delisted_active == full - survivor_only
    assert len(delisted_active) > 0  # some currently-delisted names were trading then
    assert len(full) > len(survivor_only)


def test_survivorship_gap_can_be_measured(
    session: Session, survivor_only_csv: Path, delisted_csv: Path
) -> None:
    """Acceptance gate: survivor-only and survivorship-adjusted universes both available
    and the gap can be measured."""
    load_companies(session, survivor_only_csv)
    load_delisted_seed_list(session, delisted_csv)

    as_of = date(2018, 1, 1)
    survivor_only = get_companies_active_at(session, as_of)
    survivorship_adjusted = get_universe_at(session, as_of)

    survivorship_gap = len(survivorship_adjusted) - len(survivor_only)
    assert survivorship_gap > 0
    # Specifically: at 2018-01-01, all 3 survivors plus DHFL (delisting 2021), Jet (2019),
    # Videocon (2018-06-06; still active on 2018-01-01), ABGShip (2017-12-30; just delisted)
    # = 3 + 3 = 6 expected (ABGShip just delisted before 2018-01-01)
    assert survivorship_gap >= 2  # at minimum DHFL and Jet are still trading at as_of


def test_universe_at_pre_listing_date_excludes_unlisted(
    session: Session, survivor_only_csv: Path
) -> None:
    load_companies(session, survivor_only_csv)
    pre_tcs_listing = date(1990, 1, 1)
    universe = get_universe_at(session, pre_tcs_listing)
    # Only INFY listed pre-1990? No — INFY listed 1993, TCS 2004, RELIANCE 1995.
    # On 1990-01-01 none have listing_date <= as_of_date (all are post-1990).
    assert universe == set()
