"""Canonical point-in-time loader functions.

Implements the interface specified in point_in_time_methodology.md
section 3. Every feature engine, scoring engine, and backtest function
consumes these functions; nothing else may read raw history models.

Determinism rules (point_in_time_methodology.md section 7):
- Rows sorted deterministically by primary key, then `as_known_at`
  descending, then `announcement_date` descending where applicable.
- No reliance on insertion order.
- Float values serialise to 6 decimal places when hashed.

`as_known_at` semantics (section 2): for restateable tables, return the
row with the largest `as_known_at <= as_of_date` per logical key.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..db.models_raw import (
    CorporateAction,
    Filing,
    FinancialStatement,
    IndexConstituentHistory,
    PriceDaily,
)


@dataclass(frozen=True)
class PriceRow:
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float
    adjusted_close: float | None
    volume: int | None
    delivery_volume: int | None
    delivery_percentage: float | None
    turnover: float | None


@dataclass(frozen=True)
class FinancialRow:
    period_type: str
    fiscal_year: int
    fiscal_quarter: int | None
    period_end_date: date
    announcement_date: date
    as_known_at: date
    revenue: float | None
    ebitda: float | None
    ebit: float | None
    pat: float | None
    eps: float | None
    total_assets: float | None
    total_debt: float | None
    cash: float | None
    net_worth: float | None
    operating_cash_flow: float | None
    free_cash_flow: float | None
    capex: float | None
    receivables: float | None
    inventory: float | None
    payables: float | None


@dataclass(frozen=True)
class CorporateActionRow:
    ex_date: date
    announcement_date: date | None
    action_type: str
    ratio_numerator: float | None
    ratio_denominator: float | None
    cash_amount: float | None


@dataclass(frozen=True)
class FilingRow:
    filing_id: int
    filing_type: str
    title: str
    filing_date: date
    exchange: str
    source_url: str | None
    document_hash: str | None
    parser_version: str
    source_tier: int


def get_prices_until(
    session: Session, company_id: int, as_of_date: date
) -> list[PriceRow]:
    """Daily prices for a company up to and including `as_of_date`.

    Per point_in_time_methodology.md section 1, trade_date is the
    source_timestamp; the close of T is available end-of-day T. Callers
    that need to make a decision *on* day T must clamp `as_of_date` to
    T+1 prior to calling.
    """
    stmt = (
        select(PriceDaily)
        .where(PriceDaily.company_id == company_id, PriceDaily.trade_date <= as_of_date)
        .order_by(PriceDaily.trade_date.asc())
    )
    rows = session.execute(stmt).scalars().all()
    return [
        PriceRow(
            trade_date=r.trade_date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            adjusted_close=r.adjusted_close,
            volume=r.volume,
            delivery_volume=r.delivery_volume,
            delivery_percentage=r.delivery_percentage,
            turnover=r.turnover,
        )
        for r in rows
    ]


def get_financials_available_until(
    session: Session, company_id: int, as_of_date: date
) -> list[FinancialRow]:
    """Financials with `as_known_at` semantics: per (period_type, period_end_date)
    return only the row with the largest `as_known_at <= as_of_date`.

    A restated row published after as_of_date is invisible at as_of_date;
    the loader returns the value as it was known at as_of_date, not the
    latest restated value (point_in_time_methodology.md section 2).
    """
    # Subquery: max(as_known_at) per (company_id, period_type, period_end_date)
    # restricted to rows with as_known_at <= as_of_date.
    sub = (
        select(
            FinancialStatement.company_id,
            FinancialStatement.period_type,
            FinancialStatement.period_end_date,
            func.max(FinancialStatement.as_known_at).label("max_aka"),
        )
        .where(
            FinancialStatement.company_id == company_id,
            FinancialStatement.as_known_at <= as_of_date,
        )
        .group_by(
            FinancialStatement.company_id,
            FinancialStatement.period_type,
            FinancialStatement.period_end_date,
        )
        .subquery()
    )

    stmt = (
        select(FinancialStatement)
        .join(
            sub,
            and_(
                FinancialStatement.company_id == sub.c.company_id,
                FinancialStatement.period_type == sub.c.period_type,
                FinancialStatement.period_end_date == sub.c.period_end_date,
                FinancialStatement.as_known_at == sub.c.max_aka,
            ),
        )
        .order_by(
            FinancialStatement.period_end_date.desc(),
            FinancialStatement.as_known_at.desc(),
            FinancialStatement.id.desc(),
        )
    )
    rows = session.execute(stmt).scalars().all()
    return [
        FinancialRow(
            period_type=r.period_type,
            fiscal_year=r.fiscal_year,
            fiscal_quarter=r.fiscal_quarter,
            period_end_date=r.period_end_date,
            announcement_date=r.announcement_date,
            as_known_at=r.as_known_at,
            revenue=r.revenue,
            ebitda=r.ebitda,
            ebit=r.ebit,
            pat=r.pat,
            eps=r.eps,
            total_assets=r.total_assets,
            total_debt=r.total_debt,
            cash=r.cash,
            net_worth=r.net_worth,
            operating_cash_flow=r.operating_cash_flow,
            free_cash_flow=r.free_cash_flow,
            capex=r.capex,
            receivables=r.receivables,
            inventory=r.inventory,
            payables=r.payables,
        )
        for r in rows
    ]


def get_filings_available_until(
    session: Session, company_id: int, as_of_date: date
) -> list[FilingRow]:
    stmt = (
        select(Filing)
        .where(Filing.company_id == company_id, Filing.filing_date <= as_of_date)
        .order_by(Filing.filing_date.desc(), Filing.id.desc())
    )
    rows = session.execute(stmt).scalars().all()
    return [
        FilingRow(
            filing_id=r.id,
            filing_type=r.filing_type,
            title=r.title,
            filing_date=r.filing_date,
            exchange=r.exchange,
            source_url=r.source_url,
            document_hash=r.document_hash,
            parser_version=r.parser_version,
            source_tier=r.source_tier,
        )
        for r in rows
    ]


def get_corporate_actions_until(
    session: Session,
    company_id: int,
    as_of_date: date,
    *,
    use_announcement_date: bool = False,
) -> list[CorporateActionRow]:
    """Corporate actions for a company.

    If `use_announcement_date=False` (default, for backward price
    adjustment), filters by `ex_date <= as_of_date`. If True (for forward
    decision queries that need to know an action exists), filters by
    `announcement_date <= as_of_date`. Per point_in_time_methodology.md
    section 1, the system must know which timestamp it needs.
    """
    timestamp_col = (
        CorporateAction.announcement_date if use_announcement_date else CorporateAction.ex_date
    )
    stmt = (
        select(CorporateAction)
        .where(
            CorporateAction.company_id == company_id,
            timestamp_col.is_not(None),
            timestamp_col <= as_of_date,
        )
        .order_by(CorporateAction.ex_date.asc(), CorporateAction.id.asc())
    )
    rows = session.execute(stmt).scalars().all()
    return [
        CorporateActionRow(
            ex_date=r.ex_date,
            announcement_date=r.announcement_date,
            action_type=r.action_type,
            ratio_numerator=r.ratio_numerator,
            ratio_denominator=r.ratio_denominator,
            cash_amount=r.cash_amount,
        )
        for r in rows
    ]


def get_index_constituents_as_of(
    session: Session, index_name: str, as_of_date: date
) -> set[int]:
    """Set of company_ids that are constituents of `index_name` at as_of_date.

    A row is in the index at as_of_date if `effective_from <= as_of_date`
    and (`effective_to` is null OR `effective_to > as_of_date`).
    """
    stmt = select(IndexConstituentHistory.company_id).where(
        IndexConstituentHistory.index_name == index_name,
        IndexConstituentHistory.effective_from <= as_of_date,
        or_(
            IndexConstituentHistory.effective_to.is_(None),
            IndexConstituentHistory.effective_to > as_of_date,
        ),
    )
    return set(session.execute(stmt).scalars().all())


def serialise_for_hash(payload: dict[str, Any]) -> str:
    """Canonical JSON serialisation used for `feature_snapshot_hash`.

    Sorted keys; floats rendered to 6 decimal places; dates as ISO strings;
    sets serialised as sorted lists.
    """

    def _convert(o: Any) -> Any:
        if isinstance(o, float):
            return round(o, 6)
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, set | frozenset):
            return sorted(_convert(x) for x in o)
        if isinstance(o, list | tuple):
            return [_convert(x) for x in o]
        if isinstance(o, dict):
            return {k: _convert(v) for k, v in sorted(o.items())}
        if hasattr(o, "__dict__"):  # dataclass instances etc.
            return _convert(vars(o))
        return o

    return json.dumps(_convert(payload), sort_keys=True, separators=(",", ":"))


def feature_snapshot_hash(payload: dict[str, Any]) -> str:
    """SHA-256 of the canonical serialisation. Used by historical_predictions
    to allow replay verification (point_in_time_methodology.md section 8)."""
    return hashlib.sha256(serialise_for_hash(payload).encode("utf-8")).hexdigest()
