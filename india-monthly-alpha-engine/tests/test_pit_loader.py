"""Phase 3 tests for the canonical PIT loader.

Includes the K=1000 PIT property test required by
point_in_time_methodology.md section 5 and
backtest_validity_methodology.md section 10.1.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path
from textwrap import dedent

import pytest
from sqlalchemy.orm import Session

from india_monthly_alpha_engine.ingestion.company_loader import load_companies
from india_monthly_alpha_engine.ingestion.corporate_action_loader import load_corporate_actions
from india_monthly_alpha_engine.ingestion.filing_loader import load_filings
from india_monthly_alpha_engine.ingestion.financial_loader import load_financials
from india_monthly_alpha_engine.ingestion.index_constituent_loader import load_index_constituents
from india_monthly_alpha_engine.ingestion.price_loader import load_prices
from india_monthly_alpha_engine.pit.point_in_time_loader import (
    feature_snapshot_hash,
    get_corporate_actions_until,
    get_filings_available_until,
    get_financials_available_until,
    get_index_constituents_as_of,
    get_prices_until,
    serialise_for_hash,
)


def _w(p: Path, name: str, body: str) -> Path:
    f = p / name
    f.write_text(dedent(body).lstrip("\n"), encoding="utf-8")
    return f


@pytest.fixture
def loaded_universe(session: Session, tmp_path: Path) -> tuple[Session, dict[str, int]]:
    load_companies(
        session,
        _w(
            tmp_path,
            "companies.csv",
            """
            symbol,company_name,isin,exchange,sector,industry,market_cap_category,listing_date,status
            TCS,Tata Consultancy Services,INE467B01029,NSE,IT,IT Services,large,2004-08-25,active
            INFY,Infosys,INE009A01021,NSE,IT,IT Services,large,1993-06-14,active
            """,
        ),
    )
    # Prices spanning 2024
    load_prices(
        session,
        _w(
            tmp_path,
            "prices.csv",
            """
            symbol,trade_date,open,high,low,close,volume,delivery_volume,turnover
            TCS,2024-01-02,3700.0,3720.0,3690.0,3710.0,1200000,650000,4452000000.0
            TCS,2024-04-15,3850.0,3870.0,3840.0,3860.0,1500000,800000,5790000000.0
            TCS,2024-07-01,3866.0,3890.0,3855.0,3880.0,1600000,850000,6208000000.0
            INFY,2024-04-15,1500.0,1520.0,1495.0,1510.0,2800000,1400000,4228000000.0
            """,
        ),
    )
    load_corporate_actions(
        session,
        _w(
            tmp_path,
            "ca.csv",
            """
            symbol,ex_date,announcement_date,action_type,ratio_numerator,ratio_denominator,cash_amount
            TCS,2018-06-04,2018-04-19,split,1,2,
            TCS,2024-06-21,2024-04-12,dividend,,,73.0
            """,
        ),
    )
    load_filings(
        session,
        _w(
            tmp_path,
            "fl.csv",
            """
            symbol,filing_type,title,filing_date,exchange,source_url,local_path,document_hash,parser_version,source_tier
            TCS,result,Q4 FY24 results,2024-04-12,NSE,,,abc,v0,1
            """,
        ),
    )
    load_index_constituents(
        session,
        _w(
            tmp_path,
            "ic.csv",
            """
            index_name,symbol,effective_from,effective_to,weight
            NIFTY_500,TCS,2010-01-01,,2.85
            NIFTY_500,INFY,2010-01-01,,3.20
            """,
        ),
    )

    # Q4FY24 with restatement
    load_financials(
        session,
        _w(
            tmp_path,
            "f1.csv",
            """
            symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables
            TCS,quarterly,2024,4,2024-03-31,2024-04-12,610000,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000
            """,
        ),
    )
    load_financials(
        session,
        _w(
            tmp_path,
            "f2.csv",
            """
            symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables,restatement_reason
            TCS,quarterly,2024,4,2024-03-31,2024-08-15,612500,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000,segment reclassification
            """,
        ),
    )

    # Resolve company ids
    from sqlalchemy import select

    from india_monthly_alpha_engine.db.models_raw import Company

    rows = session.execute(select(Company)).scalars().all()
    ids = {c.symbol: c.id for c in rows}
    return session, ids


def test_get_prices_until_filters_future(loaded_universe: tuple[Session, dict[str, int]]) -> None:
    s, ids = loaded_universe
    rows = get_prices_until(s, ids["TCS"], date(2024, 5, 1))
    dates = [r.trade_date for r in rows]
    assert dates == [date(2024, 1, 2), date(2024, 4, 15)]
    assert all(d <= date(2024, 5, 1) for d in dates)


def test_get_prices_includes_as_of_date(loaded_universe: tuple[Session, dict[str, int]]) -> None:
    s, ids = loaded_universe
    rows = get_prices_until(s, ids["TCS"], date(2024, 4, 15))
    assert any(r.trade_date == date(2024, 4, 15) for r in rows)


def test_financials_returns_original_pre_restatement(
    loaded_universe: tuple[Session, dict[str, int]],
) -> None:
    s, ids = loaded_universe
    # On 2024-06-30 the original announcement (2024-04-12) is visible;
    # the restatement (2024-08-15) is NOT. Loader must return revenue=610000.
    rows = get_financials_available_until(s, ids["TCS"], date(2024, 6, 30))
    assert len(rows) == 1
    assert rows[0].revenue == 610000
    assert rows[0].as_known_at == date(2024, 4, 12)


def test_financials_returns_restated_post_restatement(
    loaded_universe: tuple[Session, dict[str, int]],
) -> None:
    s, ids = loaded_universe
    rows = get_financials_available_until(s, ids["TCS"], date(2024, 9, 1))
    assert len(rows) == 1
    assert rows[0].revenue == 612500
    assert rows[0].as_known_at == date(2024, 8, 15)


def test_financials_pre_announcement_returns_empty(
    loaded_universe: tuple[Session, dict[str, int]],
) -> None:
    s, ids = loaded_universe
    rows = get_financials_available_until(s, ids["TCS"], date(2024, 4, 1))
    assert rows == []


def test_corporate_actions_filtered_by_ex_date(
    loaded_universe: tuple[Session, dict[str, int]],
) -> None:
    s, ids = loaded_universe
    rows = get_corporate_actions_until(s, ids["TCS"], date(2024, 5, 1))
    # Only the 2018 split is visible; the 2024-06-21 dividend has ex_date in the future
    assert len(rows) == 1
    assert rows[0].action_type == "split"


def test_corporate_actions_use_announcement_date(
    loaded_universe: tuple[Session, dict[str, int]],
) -> None:
    s, ids = loaded_universe
    # The dividend was announced 2024-04-12; visible at 2024-04-15 with use_announcement_date=True
    rows = get_corporate_actions_until(
        s, ids["TCS"], date(2024, 4, 15), use_announcement_date=True
    )
    types = [r.action_type for r in rows]
    assert set(types) == {"split", "dividend"}


def test_filings_filtered_by_filing_date(
    loaded_universe: tuple[Session, dict[str, int]],
) -> None:
    s, ids = loaded_universe
    pre = get_filings_available_until(s, ids["TCS"], date(2024, 4, 11))
    on = get_filings_available_until(s, ids["TCS"], date(2024, 4, 12))
    after = get_filings_available_until(s, ids["TCS"], date(2024, 5, 1))
    assert pre == []
    assert len(on) == 1
    assert len(after) == 1


def test_index_constituents_as_of(loaded_universe: tuple[Session, dict[str, int]]) -> None:
    s, ids = loaded_universe
    cs = get_index_constituents_as_of(s, "NIFTY_500", date(2024, 7, 1))
    assert ids["TCS"] in cs
    assert ids["INFY"] in cs
    pre = get_index_constituents_as_of(s, "NIFTY_500", date(2009, 12, 31))
    assert pre == set()


def test_pit_property_random_samples(loaded_universe: tuple[Session, dict[str, int]]) -> None:
    """K=1000 PIT property test (point_in_time_methodology.md section 5).

    For random (company_id, as_of_date) samples within the train+validation
    window, verify every returned row's relevant timestamp is <= as_of_date.
    """
    s, ids = loaded_universe
    rng = random.Random(42)  # deterministic seed per pit/__init__ rules
    company_ids = list(ids.values())
    # Sample over the period covered by the fixture
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    days = (end - start).days

    sample_count = 1000  # K from point_in_time_methodology.md section 5
    for _ in range(sample_count):
        cid = rng.choice(company_ids)
        offset = rng.randint(0, days)
        as_of = start + timedelta(days=offset)

        for r in get_prices_until(s, cid, as_of):
            assert r.trade_date <= as_of

        for r in get_financials_available_until(s, cid, as_of):
            assert r.as_known_at <= as_of

        for r in get_corporate_actions_until(s, cid, as_of):
            assert r.ex_date <= as_of

        for r in get_corporate_actions_until(s, cid, as_of, use_announcement_date=True):
            assert r.announcement_date is not None
            assert r.announcement_date <= as_of

        for r in get_filings_available_until(s, cid, as_of):
            assert r.filing_date <= as_of


def test_serialise_for_hash_is_deterministic() -> None:
    payload = {
        "company_id": 7,
        "as_of_date": date(2024, 6, 30),
        "metrics": {"revenue": 610000.123456789, "pat": 118000.0},
        "tags": {"high_quality", "mid_liquidity"},  # set ordering must not matter
    }
    a = serialise_for_hash(payload)
    b = serialise_for_hash(payload)
    assert a == b


def test_feature_snapshot_hash_changes_when_value_changes() -> None:
    base = {"revenue": 1000.0, "pat": 200.0}
    h1 = feature_snapshot_hash(base)
    h2 = feature_snapshot_hash({"revenue": 1000.0, "pat": 200.5})
    assert h1 != h2


def test_feature_snapshot_hash_stable_across_runs() -> None:
    payload = {"a": 1.0, "b": [1, 2, 3], "c": {"d": 4.5}}
    assert feature_snapshot_hash(payload) == feature_snapshot_hash(payload)


def test_feature_snapshot_hash_rounds_floats() -> None:
    """Per point_in_time_methodology.md section 7, floats hash at 6 decimals."""
    h1 = feature_snapshot_hash({"x": 1.0000001})
    h2 = feature_snapshot_hash({"x": 1.0000002})
    # Both round to 1.000000 at 6 decimals -> same hash
    assert h1 == h2
    h3 = feature_snapshot_hash({"x": 1.000001})
    assert h1 != h3
