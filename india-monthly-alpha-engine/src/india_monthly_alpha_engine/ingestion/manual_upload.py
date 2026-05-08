"""Manual ingestion orchestrator.

Walks a directory laid out per data_sources.md section 9:

  data/raw/companies/companies.csv
  data/raw/prices/<any>.csv
  data/raw/financials/<any>.csv
  data/raw/corporate_actions/<any>.csv
  data/raw/index_constituents/<any>.csv
  data/raw/filings/<any>.csv
  data/raw/portfolio/holdings.csv
  data/raw/portfolio/lots.csv

Companies must be loaded first because every other loader resolves
symbol -> company_id via that table.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from ._helpers import IngestStats
from .company_loader import load_companies
from .corporate_action_loader import load_corporate_actions
from .filing_loader import load_filings
from .financial_loader import load_financials
from .index_constituent_loader import load_index_constituents
from .portfolio_loader import load_portfolio_holdings, load_portfolio_lots
from .price_loader import load_prices


def _aggregate(target: IngestStats, more: IngestStats) -> None:
    target.rows_added += more.rows_added
    target.rows_updated += more.rows_updated
    target.rows_skipped += more.rows_skipped


def _glob_csv(dir_: Path) -> list[Path]:
    return sorted(p for p in dir_.glob("*.csv") if p.is_file())


def ingest_all(session: Session, raw_dir: Path) -> dict[str, IngestStats]:
    """Run every loader against `raw_dir`. Returns per-type stats."""
    results: dict[str, IngestStats] = {}

    # 1. companies first
    companies_dir = raw_dir / "companies"
    companies_stats = IngestStats()
    if companies_dir.exists():
        for csv in _glob_csv(companies_dir):
            _aggregate(companies_stats, load_companies(session, csv))
    results["companies"] = companies_stats

    # 2. all per-symbol loaders
    loader_map = {
        "prices": (load_prices, raw_dir / "prices"),
        "financials": (load_financials, raw_dir / "financials"),
        "corporate_actions": (load_corporate_actions, raw_dir / "corporate_actions"),
        "index_constituents": (load_index_constituents, raw_dir / "index_constituents"),
        "filings": (load_filings, raw_dir / "filings"),
    }
    for name, (loader, directory) in loader_map.items():
        stats = IngestStats()
        if directory.exists():
            for csv in _glob_csv(directory):
                _aggregate(stats, loader(session, csv))
        results[name] = stats

    # 3. portfolio (single CSVs by convention)
    portfolio_dir = raw_dir / "portfolio"
    holdings_stats = IngestStats()
    lots_stats = IngestStats()
    if portfolio_dir.exists():
        holdings_csv = portfolio_dir / "holdings.csv"
        lots_csv = portfolio_dir / "lots.csv"
        if holdings_csv.is_file():
            _aggregate(holdings_stats, load_portfolio_holdings(session, holdings_csv))
        if lots_csv.is_file():
            _aggregate(lots_stats, load_portfolio_lots(session, lots_csv))
    results["portfolio_holdings"] = holdings_stats
    results["portfolio_lots"] = lots_stats

    return results
