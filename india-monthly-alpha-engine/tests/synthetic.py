"""Synthetic data generator for integration / orchestrator tests.

The generator creates a deterministic, internally-consistent dataset
covering companies, prices, quarterly financials, corporate actions,
index constituents, benchmark prices, and (optionally) portfolio state.
Every helper is seeded so the same call signature always produces the
same dataset, which keeps the test determinism checks meaningful.

This is for testing only. Real production data comes from the
ingestion loaders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from sqlalchemy.orm import Session

from india_monthly_alpha_engine.db.models import BenchmarkPrice
from india_monthly_alpha_engine.db.models_raw import (
    Company,
    FinancialStatement,
    IndexConstituentHistory,
    PriceDaily,
)
from india_monthly_alpha_engine.ingestion.source_registry import register_source


@dataclass(frozen=True)
class CompanySpec:
    symbol: str
    company_name: str
    sector: str
    market_cap_category: str
    listing_date: date
    initial_price: float
    monthly_drift: float  # multiplicative monthly return mean
    monthly_vol: float  # std dev of monthly multiplicative noise
    quarterly_revenue: float
    quarterly_revenue_growth: float  # YoY rate per quarter; can be negative
    quarterly_pat_margin: float
    ocf_to_pat: float
    debt_to_equity: float


def _generate_daily_prices(spec: CompanySpec, start: date, end: date, rng: Random) -> list[tuple[date, float, float]]:
    """Return list of (trade_date, close, turnover) values for trading days."""
    out: list[tuple[date, float, float]] = []
    if start < spec.listing_date:
        start = spec.listing_date
    cur = start
    price = spec.initial_price
    daily_drift = (1.0 + spec.monthly_drift) ** (1 / 21) - 1.0
    daily_vol = spec.monthly_vol / math.sqrt(21)
    while cur <= end:
        if cur.weekday() < 5:  # weekdays only
            shock = rng.gauss(0.0, 1.0) * daily_vol
            price = max(0.5, price * (1.0 + daily_drift + shock))
            turnover = price * 100_000.0  # synthetic turnover
            out.append((cur, round(price, 2), round(turnover, 2)))
        cur = cur + timedelta(days=1)
    return out


def seed_universe(
    session: Session,
    *,
    specs: list[CompanySpec],
    history_start: date,
    as_of_date: date,
    benchmark_drift: float = 0.008,
    benchmark_vol: float = 0.04,
    seed: int = 7,
) -> dict[str, int]:
    """Seed the DB with a complete synthetic dataset and return symbol->company_id."""
    rng = Random(seed)
    src = register_source(
        session,
        source_type="synthetic_generator",
        source_url=None,
        document_hash=None,
        source_tier=1,
        parser_version="synthetic-v1",
        notes="synthetic data for integration tests; never deploy on this",
    )

    symbol_to_id: dict[str, int] = {}

    for spec in specs:
        company = Company(
            symbol=spec.symbol,
            company_name=spec.company_name,
            isin=None,
            exchange="NSE",
            sector=spec.sector,
            industry=None,
            market_cap_category=spec.market_cap_category,
            listing_date=spec.listing_date,
            status="active",
            source_id=src.id,
        )
        session.add(company)
        session.flush()
        symbol_to_id[spec.symbol] = company.id

        # Daily prices
        for d, close, turn in _generate_daily_prices(spec, history_start, as_of_date, rng):
            session.add(
                PriceDaily(
                    company_id=company.id,
                    trade_date=d,
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    adjusted_close=close,
                    volume=int(turn / max(close, 1.0)),
                    delivery_volume=int(turn / max(close, 1.0) * 0.5),
                    delivery_percentage=50.0,
                    turnover=turn,
                    source_id=src.id,
                )
            )

        # Quarterly financials, end of each quarter, announced ~45 days later
        rev = spec.quarterly_revenue / max(1.0, (1.0 + spec.quarterly_revenue_growth) ** 8)
        q = 1
        year = history_start.year
        while True:
            qe = {1: date(year, 3, 31), 2: date(year, 6, 30), 3: date(year, 9, 30), 4: date(year, 12, 31)}[q]
            ann = qe + timedelta(days=45)
            if ann > as_of_date:
                break
            rev = rev * (1.0 + spec.quarterly_revenue_growth)
            pat = rev * spec.quarterly_pat_margin
            session.add(
                FinancialStatement(
                    company_id=company.id,
                    period_type="quarterly",
                    fiscal_year=year if q != 4 else year,
                    fiscal_quarter=q,
                    period_end_date=qe,
                    announcement_date=ann,
                    as_known_at=ann,
                    supersedes_id=None,
                    restatement_reason=None,
                    revenue=rev,
                    ebitda=pat * 1.4,
                    ebit=pat * 1.2,
                    pat=pat,
                    eps=pat / 1000.0,
                    total_assets=rev * 4.0,
                    total_debt=rev * spec.debt_to_equity,
                    cash=rev * 0.10,
                    net_worth=rev * 1.0,
                    operating_cash_flow=pat * spec.ocf_to_pat,
                    free_cash_flow=pat * spec.ocf_to_pat * 0.7,
                    capex=pat * 0.3,
                    receivables=rev * 0.15,
                    inventory=rev * 0.08,
                    payables=rev * 0.10,
                    source_id=src.id,
                    parser_version="synthetic-v1",
                )
            )
            q += 1
            if q > 4:
                q = 1
                year += 1

        # Index constituent: every spec is in NIFTY_500 from listing_date onward
        session.add(
            IndexConstituentHistory(
                index_name="NIFTY_500",
                company_id=company.id,
                symbol=spec.symbol,
                effective_from=spec.listing_date,
                effective_to=None,
                weight=1.0 / max(1, len(specs)),
                source_id=src.id,
            )
        )

    # Benchmark prices (Nifty 500 TRI proxy): synthetic random walk
    bench_close = 1000.0
    daily_drift = (1.0 + benchmark_drift) ** (1 / 21) - 1.0
    daily_vol = benchmark_vol / math.sqrt(21)
    cur = history_start
    while cur <= as_of_date:
        if cur.weekday() < 5:
            bench_close = max(100.0, bench_close * (1.0 + daily_drift + rng.gauss(0.0, 1.0) * daily_vol))
            session.add(
                BenchmarkPrice(
                    index_name="NIFTY_500_TRI",
                    trade_date=cur,
                    close=bench_close,
                    tri_close=bench_close,
                    source_id=src.id,
                )
            )
        cur = cur + timedelta(days=1)

    session.flush()
    return symbol_to_id


def standard_specs(*, as_of: date, count: int = 12) -> list[CompanySpec]:
    """Return a diverse set of `count` company specs covering different
    quality / growth / valuation / liquidity profiles."""
    listing = date(as_of.year - 12, 1, 1)
    out: list[CompanySpec] = []
    sectors = ["IT", "financials", "consumer_discretionary", "consumer_staples", "healthcare", "industrials"]
    for i in range(count):
        # Shape the spec along several axes so each company is meaningfully different
        quality = (i % 4) / 3.0  # 0..1
        growth = ((i // 4) % 3 - 1) * 0.04  # -4%, 0%, +4% per quarter
        size_buckets = ["large", "mid", "small", "micro"]
        size = size_buckets[i % 4]
        out.append(
            CompanySpec(
                symbol=f"SYN{i:02d}",
                company_name=f"Synthetic Co {i}",
                sector=sectors[i % len(sectors)],
                market_cap_category=size,
                listing_date=listing,
                initial_price=100.0 + i * 13.0,
                monthly_drift=0.005 + quality * 0.012,
                monthly_vol=0.06 + (1 - quality) * 0.04,
                quarterly_revenue=1000.0 * (i + 1),
                quarterly_revenue_growth=growth,
                quarterly_pat_margin=0.05 + quality * 0.15,
                ocf_to_pat=0.6 + quality * 0.6,
                debt_to_equity=0.8 - quality * 0.6,
            )
        )
    return out
