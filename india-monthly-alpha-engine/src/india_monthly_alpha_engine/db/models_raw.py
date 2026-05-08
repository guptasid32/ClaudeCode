"""Raw history models — only `pit/` and `ingestion/` may import this module.

The import-linter contract `pit is the only consumer of raw history models`
in pyproject.toml forbids `features`, `engines`, `backtest`, `historical`,
`reports`, and `ui` from importing this module. Everything else consumes
raw history through the PIT loader (Phase 3).

Source-tier ordering, per-data-type primary sources, and `as_known_at`
semantics for restated rows are specified in:
- docs/data_sources.md
- docs/point_in_time_methodology.md
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("symbol", "exchange", name="uq_company_symbol_exchange"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(256), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    exchange: Mapped[str] = mapped_column(String(8), nullable=False, default="NSE")
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    market_cap_category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    listing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisting_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    source_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("sources.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class DelistingEvent(Base):
    """Per backtest_validity_methodology.md section 4.2 and data_sources.md section 6.

    Records the distress / delisting / recapitalisation event for survivorship-
    correct universe construction (backtest_validity_methodology.md section 3.1).
    """

    __tablename__ = "delisting_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    event_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    recovery_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PriceDaily(Base):
    __tablename__ = "prices_daily"
    __table_args__ = (
        UniqueConstraint("company_id", "trade_date", name="uq_price_company_trade_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class FinancialStatement(Base):
    """Append-only financial-statement rows with `as_known_at` semantics.

    A restatement creates a new row with the new `as_known_at` and a
    `supersedes_id` pointing at the prior row. PIT loader returns the
    row with the largest `as_known_at <= as_of_date` per
    (company_id, period_type, period_end_date). See
    docs/point_in_time_methodology.md section 2.
    """

    __tablename__ = "financial_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    period_type: Mapped[str] = mapped_column(String(8), nullable=False)  # quarterly / annual
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    announcement_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    as_known_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    supersedes_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("financial_statements.id"), nullable=True
    )
    restatement_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebitda: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebit: Mapped[float | None] = mapped_column(Float, nullable=True)
    pat: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_worth: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    receivables: Mapped[float | None] = mapped_column(Float, nullable=True)
    inventory: Mapped[float | None] = mapped_column(Float, nullable=True)
    payables: Mapped[float | None] = mapped_column(Float, nullable=True)

    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "ex_date", "action_type", name="uq_corp_action_company_date_type"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    announcement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    action_type: Mapped[str] = mapped_column(String(16), nullable=False)
    ratio_numerator: Mapped[float | None] = mapped_column(Float, nullable=True)
    ratio_denominator: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class IndexConstituentHistory(Base):
    __tablename__ = "index_constituents_history"
    __table_args__ = (
        UniqueConstraint(
            "index_name", "company_id", "effective_from", name="uq_index_constituent"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    index_name: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id"), nullable=False, index=True
    )
    filing_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    exchange: Mapped[str] = mapped_column(String(8), nullable=False, default="NSE")
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_text_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v0")
    source_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
