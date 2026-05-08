"""Phase 2 acceptance tests for manual ingestion.

Acceptance gates from v2 plan section 21 Phase 2:
- can load a small universe
- each data point has source metadata
- data timestamps available for PIT replay
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from textwrap import dedent

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from india_monthly_alpha_engine.db.models import (
    PortfolioHolding,
    PortfolioLot,
    Source,
)
from india_monthly_alpha_engine.db.models_raw import (
    Company,
    CorporateAction,
    Filing,
    FinancialStatement,
    IndexConstituentHistory,
    PriceDaily,
)
from india_monthly_alpha_engine.ingestion.company_loader import load_companies
from india_monthly_alpha_engine.ingestion.corporate_action_loader import load_corporate_actions
from india_monthly_alpha_engine.ingestion.filing_loader import load_filings
from india_monthly_alpha_engine.ingestion.financial_loader import load_financials
from india_monthly_alpha_engine.ingestion.index_constituent_loader import load_index_constituents
from india_monthly_alpha_engine.ingestion.manual_upload import ingest_all
from india_monthly_alpha_engine.ingestion.portfolio_loader import (
    load_portfolio_holdings,
    load_portfolio_lots,
)
from india_monthly_alpha_engine.ingestion.price_loader import load_prices


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(dedent(body).lstrip("\n"), encoding="utf-8")
    return p


@pytest.fixture
def companies_csv(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        "companies.csv",
        """
        symbol,company_name,isin,exchange,sector,industry,market_cap_category,listing_date,status
        TCS,Tata Consultancy Services,INE467B01029,NSE,IT,IT Services,large,2004-08-25,active
        RELIANCE,Reliance Industries,INE002A01018,NSE,energy,Refineries,large,1995-11-29,active
        """,
    )


@pytest.fixture
def loaded_companies(session: Session, companies_csv: Path) -> Session:
    load_companies(session, companies_csv, source_url="test://companies")
    session.flush()
    return session


def test_companies_loaded(loaded_companies: Session) -> None:
    rows = loaded_companies.execute(select(Company)).scalars().all()
    assert {c.symbol for c in rows} == {"TCS", "RELIANCE"}
    assert all(c.source_id is not None for c in rows)


def test_source_registry_records_metadata(loaded_companies: Session) -> None:
    sources = loaded_companies.execute(select(Source)).scalars().all()
    assert len(sources) == 1
    src = sources[0]
    assert src.source_type == "companies_csv"
    assert src.document_hash is not None
    assert len(src.document_hash) == 64
    assert src.rows_added == 2
    assert src.ingest_version == 1
    assert src.parser_version == "v0"
    assert src.source_tier == 1
    assert src.source_url == "test://companies"


def test_companies_idempotent(session: Session, companies_csv: Path) -> None:
    load_companies(session, companies_csv)
    load_companies(session, companies_csv)
    rows = session.execute(select(Company)).scalars().all()
    assert len(rows) == 2  # second load updates, does not duplicate


def test_prices_loaded(loaded_companies: Session, tmp_path: Path) -> None:
    csv = _write(
        tmp_path,
        "prices.csv",
        """
        symbol,trade_date,open,high,low,close,volume,delivery_volume,turnover
        TCS,2024-06-28,3850.0,3870.0,3840.0,3865.5,1500000,800000,5800000000.0
        TCS,2024-07-01,3866.0,3890.0,3855.0,3880.0,1600000,850000,6200000000.0
        RELIANCE,2024-07-01,3050.0,3070.0,3040.0,3060.0,2200000,1100000,6720000000.0
        """,
    )
    stats = load_prices(loaded_companies, csv)
    assert stats.rows_added == 3
    rows = loaded_companies.execute(select(PriceDaily)).scalars().all()
    assert len(rows) == 3
    # source_id present on every row, trade_date set, adjusted_close defaults to close
    assert all(r.source_id for r in rows)
    assert all(r.trade_date is not None for r in rows)
    assert all(r.adjusted_close == r.close for r in rows)


def test_prices_skip_duplicates(loaded_companies: Session, tmp_path: Path) -> None:
    csv = _write(
        tmp_path,
        "prices.csv",
        """
        symbol,trade_date,open,high,low,close,volume,delivery_volume,turnover
        TCS,2024-07-01,3866.0,3890.0,3855.0,3880.0,1600000,850000,6200000000.0
        """,
    )
    load_prices(loaded_companies, csv)
    stats2 = load_prices(loaded_companies, csv)
    assert stats2.rows_added == 0
    assert stats2.rows_skipped == 1


def test_financials_initial_load(loaded_companies: Session, tmp_path: Path) -> None:
    csv = _write(
        tmp_path,
        "financials.csv",
        """
        symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables
        TCS,quarterly,2024,4,2024-03-31,2024-04-12,610000,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000
        TCS,quarterly,2025,1,2024-06-30,2024-07-11,625000,121000,165000,182000,9100,17500,91000,142000,121000,15500,41000,3100,31000
        """,
    )
    stats = load_financials(loaded_companies, csv)
    assert stats.rows_added == 2
    rows = (
        loaded_companies.execute(select(FinancialStatement).order_by(FinancialStatement.id))
        .scalars()
        .all()
    )
    assert all(r.as_known_at == r.announcement_date for r in rows)
    assert all(r.supersedes_id is None for r in rows)


def test_financials_restatement_creates_new_row(
    loaded_companies: Session, tmp_path: Path
) -> None:
    csv1 = _write(
        tmp_path,
        "f1.csv",
        """
        symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables
        TCS,quarterly,2024,4,2024-03-31,2024-04-12,610000,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000
        """,
    )
    load_financials(loaded_companies, csv1)

    # Restatement: revenue corrected from 610000 to 612500
    csv2 = _write(
        tmp_path,
        "f2.csv",
        """
        symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables,restatement_reason
        TCS,quarterly,2024,4,2024-03-31,2024-08-15,612500,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000,segment reclassification
        """,
    )
    load_financials(loaded_companies, csv2)

    rows = (
        loaded_companies.execute(
            select(FinancialStatement).order_by(FinancialStatement.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2  # original kept, restatement appended
    original, restated = rows
    assert original.as_known_at == date(2024, 4, 12)
    assert original.revenue == 610000
    assert restated.as_known_at == date(2024, 8, 15)
    assert restated.revenue == 612500
    assert restated.supersedes_id == original.id
    assert restated.restatement_reason == "segment reclassification"


def test_financials_skip_when_values_unchanged(
    loaded_companies: Session, tmp_path: Path
) -> None:
    csv = _write(
        tmp_path,
        "f.csv",
        """
        symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables
        TCS,quarterly,2024,4,2024-03-31,2024-04-12,610000,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000
        """,
    )
    load_financials(loaded_companies, csv)
    stats2 = load_financials(loaded_companies, csv)
    assert stats2.rows_added == 0
    assert stats2.rows_skipped == 1


def test_corporate_actions_loaded(loaded_companies: Session, tmp_path: Path) -> None:
    csv = _write(
        tmp_path,
        "ca.csv",
        """
        symbol,ex_date,announcement_date,action_type,ratio_numerator,ratio_denominator,cash_amount
        TCS,2024-06-21,2024-04-12,dividend,,,73.0
        TCS,2018-06-04,2018-04-19,split,1,2,
        RELIANCE,2024-10-28,2024-09-05,bonus,1,1,
        """,
    )
    stats = load_corporate_actions(loaded_companies, csv)
    assert stats.rows_added == 3
    rows = loaded_companies.execute(select(CorporateAction)).scalars().all()
    types = {r.action_type for r in rows}
    assert types == {"dividend", "split", "bonus"}


def test_corporate_actions_unsupported_type_raises(
    loaded_companies: Session, tmp_path: Path
) -> None:
    csv = _write(
        tmp_path,
        "ca.csv",
        """
        symbol,ex_date,announcement_date,action_type,ratio_numerator,ratio_denominator,cash_amount
        TCS,2024-06-21,2024-04-12,unicorn,,,
        """,
    )
    with pytest.raises(ValueError, match="unsupported corporate action"):
        load_corporate_actions(loaded_companies, csv)


def test_index_constituents_loaded(loaded_companies: Session, tmp_path: Path) -> None:
    csv = _write(
        tmp_path,
        "ic.csv",
        """
        index_name,symbol,effective_from,effective_to,weight
        NIFTY_500,TCS,2010-01-01,,2.85
        NIFTY_500,RELIANCE,2010-01-01,,9.10
        """,
    )
    stats = load_index_constituents(loaded_companies, csv)
    assert stats.rows_added == 2
    rows = loaded_companies.execute(select(IndexConstituentHistory)).scalars().all()
    assert {r.symbol for r in rows} == {"TCS", "RELIANCE"}
    assert all(r.effective_from == date(2010, 1, 1) for r in rows)


def test_filings_loaded(loaded_companies: Session, tmp_path: Path) -> None:
    csv = _write(
        tmp_path,
        "fl.csv",
        """
        symbol,filing_type,title,filing_date,exchange,source_url,local_path,document_hash,parser_version,source_tier
        TCS,result,Q4 FY24 results,2024-04-12,NSE,https://nse.example/tcs-q4,/tmp/tcs.pdf,abc123,v0,1
        TCS,announcement,Dividend declaration,2024-04-12,NSE,https://nse.example/tcs-div,,xyz789,v0,1
        """,
    )
    stats = load_filings(loaded_companies, csv)
    assert stats.rows_added == 2
    rows = loaded_companies.execute(select(Filing)).scalars().all()
    assert {r.filing_type for r in rows} == {"result", "announcement"}
    assert all(r.source_tier == 1 for r in rows)


def test_portfolio_loaded(loaded_companies: Session, tmp_path: Path) -> None:
    holdings_csv = _write(
        tmp_path,
        "holdings.csv",
        """
        symbol,quantity,average_price,sector,entry_date,thesis_status
        TCS,10,3500.0,IT,2023-05-12,intact
        """,
    )
    lots_csv = _write(
        tmp_path,
        "lots.csv",
        """
        symbol,quantity,acquisition_date,cost_per_share,total_cost,pre_grandfather_fmv
        TCS,5,2023-05-12,3400.0,17000.0,
        TCS,5,2024-01-15,3600.0,18000.0,
        """,
    )
    h_stats = load_portfolio_holdings(loaded_companies, holdings_csv)
    l_stats = load_portfolio_lots(loaded_companies, lots_csv)
    assert h_stats.rows_added == 1
    assert l_stats.rows_added == 2
    holdings = loaded_companies.execute(select(PortfolioHolding)).scalars().all()
    lots = (
        loaded_companies.execute(select(PortfolioLot).order_by(PortfolioLot.acquisition_date))
        .scalars()
        .all()
    )
    assert holdings[0].symbol == "TCS"
    assert holdings[0].thesis_status == "intact"
    assert sum(lot.quantity for lot in lots) == 10


def test_ingest_all_orchestrator(loaded_companies: Session, tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "companies").mkdir(parents=True)
    (raw / "prices").mkdir()
    (raw / "corporate_actions").mkdir()
    (raw / "portfolio").mkdir()

    _write(
        raw / "companies",
        "c.csv",
        """
        symbol,company_name,isin,exchange,sector,industry,market_cap_category,listing_date,status
        INFY,Infosys,INE009A01021,NSE,IT,IT Services,large,1993-06-14,active
        """,
    )
    _write(
        raw / "prices",
        "p.csv",
        """
        symbol,trade_date,open,high,low,close,volume,delivery_volume,turnover
        INFY,2024-07-01,1525.0,1545.0,1518.0,1538.0,3000000,1500000,4615000000.0
        """,
    )
    _write(
        raw / "corporate_actions",
        "ca.csv",
        """
        symbol,ex_date,announcement_date,action_type,ratio_numerator,ratio_denominator,cash_amount
        INFY,2024-06-03,2024-04-18,dividend,,,28.0
        """,
    )
    _write(
        raw / "portfolio",
        "holdings.csv",
        """
        symbol,quantity,average_price,sector,entry_date,thesis_status
        INFY,12,1450.0,IT,2024-02-10,intact
        """,
    )

    results = ingest_all(loaded_companies, raw)
    assert results["companies"].rows_added >= 1
    assert results["prices"].rows_added == 1
    assert results["corporate_actions"].rows_added == 1
    assert results["portfolio_holdings"].rows_added == 1
    # No financials, index constituents, filings, or lots in this fixture
    assert results["financials"].rows_added == 0
    assert results["index_constituents"].rows_added == 0
    assert results["filings"].rows_added == 0
    assert results["portfolio_lots"].rows_added == 0


def test_pit_timestamps_present_on_every_table(loaded_companies: Session, tmp_path: Path) -> None:
    """Phase 2 acceptance: every ingested data point carries a usable PIT timestamp."""
    # Load one row in each raw table
    _write(
        tmp_path,
        "p.csv",
        """
        symbol,trade_date,open,high,low,close,volume,delivery_volume,turnover
        TCS,2024-07-01,3866.0,3890.0,3855.0,3880.0,1600000,850000,6200000000.0
        """,
    )
    load_prices(loaded_companies, tmp_path / "p.csv")

    _write(
        tmp_path,
        "f.csv",
        """
        symbol,period_type,fiscal_year,fiscal_quarter,period_end_date,announcement_date,revenue,pat,ebitda,total_assets,total_debt,cash,net_worth,operating_cash_flow,free_cash_flow,capex,receivables,inventory,payables
        TCS,quarterly,2024,4,2024-03-31,2024-04-12,610000,118000,160000,180000,9000,17000,90000,140000,120000,15000,40000,3000,30000
        """,
    )
    load_financials(loaded_companies, tmp_path / "f.csv")

    _write(
        tmp_path,
        "ca.csv",
        """
        symbol,ex_date,announcement_date,action_type,ratio_numerator,ratio_denominator,cash_amount
        TCS,2024-06-21,2024-04-12,dividend,,,73.0
        """,
    )
    load_corporate_actions(loaded_companies, tmp_path / "ca.csv")

    _write(
        tmp_path,
        "ic.csv",
        """
        index_name,symbol,effective_from,effective_to,weight
        NIFTY_500,TCS,2010-01-01,,2.85
        """,
    )
    load_index_constituents(loaded_companies, tmp_path / "ic.csv")

    _write(
        tmp_path,
        "fl.csv",
        """
        symbol,filing_type,title,filing_date,exchange,source_url,local_path,document_hash,parser_version,source_tier
        TCS,result,Q4 FY24 results,2024-04-12,NSE,https://nse.example/x,/tmp/x.pdf,abc,v0,1
        """,
    )
    load_filings(loaded_companies, tmp_path / "fl.csv")

    # Every PIT-relevant timestamp must be set on every row
    for row in loaded_companies.execute(select(PriceDaily)).scalars():
        assert row.trade_date is not None
        assert row.source_id is not None
    for row in loaded_companies.execute(select(FinancialStatement)).scalars():
        assert row.announcement_date is not None
        assert row.as_known_at is not None
        assert row.period_end_date is not None
    for row in loaded_companies.execute(select(CorporateAction)).scalars():
        assert row.ex_date is not None
    for row in loaded_companies.execute(select(IndexConstituentHistory)).scalars():
        assert row.effective_from is not None
    for row in loaded_companies.execute(select(Filing)).scalars():
        assert row.filing_date is not None
