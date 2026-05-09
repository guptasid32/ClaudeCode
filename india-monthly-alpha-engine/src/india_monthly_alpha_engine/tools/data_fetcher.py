"""Real-data fetcher: pulls Indian equity prices, actions, and basic financials
from free public sources.

Primary backend: yfinance (works for Indian stocks via .NS / .BO suffix).
Backup: NSE archives (best-effort; URL formats change occasionally).

This module is in `tools/` rather than `ingestion/` because it bridges
network calls into the ingestion loaders. The ingestion loaders themselves
remain pure CSV consumers — that boundary keeps unit tests fast and
deterministic.

All fetched data is written through the source registry, so the audit
trail (source URL, ingestion timestamp, document hash, parser version)
is preserved and queries can later be reproduced.

Usage:

    python -m india_monthly_alpha_engine.tools.data_fetcher bulk \
        --start 2014-01-01 --symbols-file data/raw/companies/nifty500.txt
    python -m india_monthly_alpha_engine.tools.data_fetcher refresh \
        --random-symbols 30 --extend-history-years 1
"""

from __future__ import annotations

import argparse
import hashlib
import random
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import get_settings
from ..app.logging_config import configure_logging, get_logger
from ..db.models import BenchmarkPrice
from ..db.models_raw import (
    Company,
    CorporateAction,
    FinancialStatement,
    IndexConstituentHistory,
    PriceDaily,
)
from ..db.session import get_session
from ..ingestion.source_registry import finalize_source, register_source

# A starter Nifty 500 symbol list. The user can override via --symbols-file.
# This is intentionally short for a first run; expand to the full 500 by
# pasting the NSE Indices methodology page.
_DEFAULT_SYMBOLS = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "HINDUNILVR",
    "ITC",
    "LT",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "AXISBANK",
    "BAJFINANCE",
    "ASIANPAINT",
    "MARUTI",
    "HCLTECH",
    "WIPRO",
    "SUNPHARMA",
    "ULTRACEMCO",
    "TITAN",
    "NESTLEIND",
    "POWERGRID",
    "NTPC",
    "ONGC",
    "TATASTEEL",
    "JSWSTEEL",
    "BAJAJFINSV",
    "TECHM",
    "HDFC",
    "M&M",
]

# Known distressed / delisted seeds. Per data_sources.md section 6, the
# user is expected to grow this to 50+ confirmed entries with verified
# event dates. The defaults below are starter cases — verify dates
# before using them in any final backtest.
_DEFAULT_DELISTED = [
    # symbol, name, sector, market_cap_category, listing_date, delisting_date, event_type
    ("DHFL", "Dewan Housing Finance", "financials", "mid", "1985-12-31", "2021-07-15", "IBC"),
    ("JET", "Jet Airways", "industrials", "mid", "2005-12-15", "2019-06-20", "NCLT"),
    ("VIDEOIND", "Videocon Industries", "consumer_discretionary", "mid", "1990-01-01", "2018-06-06", "NCLT"),
    ("RCOM", "Reliance Communications", "communications", "large", "2006-03-06", "2020-08-13", "NCLT"),
    ("ABGSHIP", "ABG Shipyard", "industrials", "small", "2007-12-28", "2017-12-30", "NCLT"),
    ("EROSMEDIA", "Eros International Media", "communications", "small", "2010-09-29", "2024-01-15", "regulatory_delisting"),
]


def _hash_payload(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()


def _yf_safe_import() -> object | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    return yf


def upsert_company(
    session: Session,
    *,
    symbol: str,
    company_name: str | None,
    sector: str | None,
    market_cap_category: str | None,
    listing_date: date | None,
    source_id: int,
    delisting_date: date | None = None,
    status: str = "active",
) -> int:
    existing = session.execute(
        select(Company).where(Company.symbol == symbol, Company.exchange == "NSE")
    ).scalar_one_or_none()
    if existing is not None:
        if delisting_date and not existing.delisting_date:
            existing.delisting_date = delisting_date
            existing.status = "delisted"
        return existing.id
    company = Company(
        symbol=symbol,
        company_name=company_name or symbol,
        exchange="NSE",
        sector=sector,
        market_cap_category=market_cap_category,
        listing_date=listing_date,
        delisting_date=delisting_date,
        status=status,
        source_id=source_id,
    )
    session.add(company)
    session.flush()
    return company.id


def fetch_prices_yfinance(
    session: Session,
    *,
    symbols: list[str],
    start: date,
    end: date,
    log,
) -> tuple[int, int]:
    """Fetch daily OHLCV via yfinance and write to prices_daily.

    Returns (rows_added, symbols_failed).
    """
    yf = _yf_safe_import()
    if yf is None:
        raise SystemExit("yfinance not installed. Re-run pip install -e \".[data]\"")

    src = register_source(
        session,
        source_type="yfinance_prices",
        source_url="https://query2.finance.yahoo.com/v8/finance/chart/",
        document_hash=_hash_payload([",".join(sorted(symbols)), start.isoformat(), end.isoformat()]),
        source_tier=4,  # third-party aggregator
        parser_version="yfinance-v1",
    )

    rows_added = 0
    failed = 0
    for sym in symbols:
        ticker_yf = sym + ".NS"
        try:
            ticker = yf.Ticker(ticker_yf)
            info = getattr(ticker, "info", {}) or {}
            company_name = info.get("longName") or info.get("shortName") or sym
            sector_yf = info.get("sector")
            sector_map = {
                "Technology": "IT",
                "Financial Services": "financials",
                "Industrials": "industrials",
                "Healthcare": "healthcare",
                "Consumer Cyclical": "consumer_discretionary",
                "Consumer Defensive": "consumer_staples",
                "Energy": "energy",
                "Basic Materials": "materials",
                "Utilities": "utilities",
                "Communication Services": "communications",
                "Real Estate": "real_estate",
            }
            sector = sector_map.get(sector_yf, "unknown")
            market_cap = info.get("marketCap")
            if market_cap:
                cr = market_cap / 1e7
                if cr >= 50_000:
                    cap_cat = "large"
                elif cr >= 15_000:
                    cap_cat = "mid"
                elif cr >= 2_000:
                    cap_cat = "small"
                else:
                    cap_cat = "micro"
            else:
                cap_cat = None

            cid = upsert_company(
                session,
                symbol=sym,
                company_name=company_name,
                sector=sector,
                market_cap_category=cap_cat,
                listing_date=None,
                source_id=src.id,
            )

            hist = ticker.history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,
                actions=True,
            )
            if hist is None or hist.empty:
                failed += 1
                continue

            for ts, row in hist.iterrows():
                trade_date = ts.date() if hasattr(ts, "date") else ts
                close = float(row["Close"])
                if close <= 0:
                    continue
                existing = session.execute(
                    select(PriceDaily).where(
                        PriceDaily.company_id == cid, PriceDaily.trade_date == trade_date
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                volume = int(row["Volume"]) if not pd_isna(row.get("Volume")) else None
                turnover = (volume * close) if volume else None
                session.add(
                    PriceDaily(
                        company_id=cid,
                        trade_date=trade_date,
                        open=float(row["Open"]) if not pd_isna(row.get("Open")) else None,
                        high=float(row["High"]) if not pd_isna(row.get("High")) else None,
                        low=float(row["Low"]) if not pd_isna(row.get("Low")) else None,
                        close=close,
                        adjusted_close=float(row.get("Adj Close", close)) if not pd_isna(row.get("Adj Close")) else close,
                        volume=volume,
                        delivery_volume=None,
                        delivery_percentage=None,
                        turnover=turnover,
                        source_id=src.id,
                    )
                )
                rows_added += 1

            # Corporate actions: dividends and splits
            try:
                actions_df = ticker.actions
                if actions_df is not None and not actions_df.empty:
                    for ts, row in actions_df.iterrows():
                        ex_date = ts.date() if hasattr(ts, "date") else ts
                        div = row.get("Dividends", 0.0)
                        split = row.get("Stock Splits", 0.0)
                        if div and div > 0:
                            existing_a = session.execute(
                                select(CorporateAction).where(
                                    CorporateAction.company_id == cid,
                                    CorporateAction.ex_date == ex_date,
                                    CorporateAction.action_type == "dividend",
                                )
                            ).scalar_one_or_none()
                            if existing_a is None:
                                session.add(
                                    CorporateAction(
                                        company_id=cid,
                                        ex_date=ex_date,
                                        announcement_date=ex_date - timedelta(days=30),
                                        action_type="dividend",
                                        cash_amount=float(div),
                                        source_id=src.id,
                                    )
                                )
                        if split and split > 0 and split != 1:
                            existing_a = session.execute(
                                select(CorporateAction).where(
                                    CorporateAction.company_id == cid,
                                    CorporateAction.ex_date == ex_date,
                                    CorporateAction.action_type == "split",
                                )
                            ).scalar_one_or_none()
                            if existing_a is None:
                                # Yahoo's split factor is "new per old". For a 2-for-1, factor=2.
                                session.add(
                                    CorporateAction(
                                        company_id=cid,
                                        ex_date=ex_date,
                                        announcement_date=ex_date - timedelta(days=30),
                                        action_type="split",
                                        ratio_numerator=1.0,
                                        ratio_denominator=float(split),
                                        source_id=src.id,
                                    )
                                )
            except Exception as e:
                log.warning("corp_actions.failed", symbol=sym, error=str(e))

            log.info("yf.fetched", symbol=sym, rows=len(hist))
            session.flush()
        except Exception as e:
            failed += 1
            log.error("yf.symbol_failed", symbol=sym, error=str(e))

    finalize_source(session, src, files_loaded=len(symbols), rows_added=rows_added)
    return rows_added, failed


def pd_isna(v: object) -> bool:
    """Lightweight NaN check that does not require importing pandas globally."""
    if v is None:
        return True
    try:
        return v != v  # NaN != NaN
    except Exception:
        return False


def fetch_benchmark_yfinance(
    session: Session, *, start: date, end: date, log, index_yahoo_symbol: str = "^CRSLDX"
) -> int:
    """Fetch a Nifty 500 proxy series via yfinance.

    `^CRSLDX` is Yahoo's Nifty 500 ticker. It is PRI, not TRI; for a true
    Total Return series, swap in your own CSV via tools.load_benchmark.
    """
    yf = _yf_safe_import()
    if yf is None:
        raise SystemExit("yfinance not installed. Re-run pip install -e \".[data]\"")

    src = register_source(
        session,
        source_type="yfinance_benchmark",
        source_url=f"yahoo://{index_yahoo_symbol}",
        document_hash=_hash_payload([index_yahoo_symbol, start.isoformat(), end.isoformat()]),
        source_tier=4,
        parser_version="yfinance-v1",
        notes="yahoo Nifty 500 PRI; replace with TRI series for honest alpha measurement",
    )

    ticker = yf.Ticker(index_yahoo_symbol)
    hist = ticker.history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat())
    if hist is None or hist.empty:
        log.error("yf.benchmark_empty", index=index_yahoo_symbol)
        return 0

    rows_added = 0
    for ts, row in hist.iterrows():
        trade_date = ts.date() if hasattr(ts, "date") else ts
        close = float(row["Close"])
        existing = session.execute(
            select(BenchmarkPrice).where(
                BenchmarkPrice.index_name == "NIFTY_500_TRI",
                BenchmarkPrice.trade_date == trade_date,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(
            BenchmarkPrice(
                index_name="NIFTY_500_TRI",
                trade_date=trade_date,
                close=close,
                tri_close=close,  # PRI as proxy until proper TRI loaded
                source_id=src.id,
            )
        )
        rows_added += 1

    finalize_source(session, src, rows_added=rows_added)
    log.info("yf.benchmark_loaded", rows=rows_added)
    return rows_added


def seed_index_constituents(session: Session, *, symbols: list[str], source_id: int) -> int:
    """All symbols become NIFTY_500 constituents from a far past date.

    For a proper backtest you'd need the historical reconstitution table.
    For first-run convenience this uses a static effective_from per symbol.
    """
    rows_added = 0
    for sym in symbols:
        cid = session.execute(
            select(Company.id).where(Company.symbol == sym, Company.exchange == "NSE")
        ).scalar_one_or_none()
        if cid is None:
            continue
        existing = session.execute(
            select(IndexConstituentHistory).where(
                IndexConstituentHistory.index_name == "NIFTY_500",
                IndexConstituentHistory.company_id == cid,
            )
        ).scalar_one_or_none()
        if existing is not None:
            continue
        session.add(
            IndexConstituentHistory(
                index_name="NIFTY_500",
                company_id=cid,
                symbol=sym,
                effective_from=date(2000, 1, 1),
                effective_to=None,
                weight=1.0 / max(1, len(symbols)),
                source_id=source_id,
            )
        )
        rows_added += 1
    return rows_added


def seed_delisted_defaults(session: Session, *, source_id: int, log) -> int:
    """Seed the delisted-companies starter list from the curated default."""
    rows_added = 0
    for sym, name, sector, cap, listed, delist, event in _DEFAULT_DELISTED:
        try:
            upsert_company(
                session,
                symbol=sym,
                company_name=name,
                sector=sector,
                market_cap_category=cap,
                listing_date=date.fromisoformat(listed),
                source_id=source_id,
                delisting_date=date.fromisoformat(delist),
                status="delisted",
            )
            log.info("delisted.seeded", symbol=sym, event=event)
            rows_added += 1
        except Exception as e:
            log.warning("delisted.seed_failed", symbol=sym, error=str(e))
    return rows_added


def fetch_quarterly_financials(
    session: Session, *, symbols: list[str], log, source_id: int
) -> int:
    """Best-effort quarterly financials from yfinance.

    Many Indian listings have only partial coverage. Missing fields are
    left null and treated by the Evidence Quality rubric accordingly.
    """
    yf = _yf_safe_import()
    if yf is None:
        return 0
    rows_added = 0
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym + ".NS")
            qs = ticker.quarterly_financials  # may be empty
            qbs = ticker.quarterly_balance_sheet
            qcf = ticker.quarterly_cashflow
            if qs is None or qs.empty:
                continue
            cid = session.execute(
                select(Company.id).where(Company.symbol == sym, Company.exchange == "NSE")
            ).scalar_one_or_none()
            if cid is None:
                continue
            for col in qs.columns:
                pe = col.date() if hasattr(col, "date") else col
                ann = pe + timedelta(days=45)
                rev_row = qs.get(col)
                rev = float(rev_row.get("Total Revenue", 0.0) or 0.0) if rev_row is not None else 0.0
                pat = float(rev_row.get("Net Income", 0.0) or 0.0) if rev_row is not None else 0.0
                ebitda = float(rev_row.get("EBITDA", 0.0) or 0.0) if rev_row is not None else 0.0
                ocf = 0.0
                if qcf is not None and not qcf.empty and col in qcf.columns:
                    cf_row = qcf.get(col)
                    ocf = float(cf_row.get("Operating Cash Flow", 0.0) or 0.0) if cf_row is not None else 0.0
                debt = 0.0
                cash = 0.0
                eq = 0.0
                if qbs is not None and not qbs.empty and col in qbs.columns:
                    bs_row = qbs.get(col)
                    debt = float(bs_row.get("Total Debt", 0.0) or 0.0) if bs_row is not None else 0.0
                    cash = float(bs_row.get("Cash And Cash Equivalents", 0.0) or 0.0) if bs_row is not None else 0.0
                    eq = float(bs_row.get("Stockholders Equity", 0.0) or 0.0) if bs_row is not None else 0.0

                existing = session.execute(
                    select(FinancialStatement).where(
                        FinancialStatement.company_id == cid,
                        FinancialStatement.period_end_date == pe,
                        FinancialStatement.period_type == "quarterly",
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                session.add(
                    FinancialStatement(
                        company_id=cid,
                        period_type="quarterly",
                        fiscal_year=pe.year,
                        fiscal_quarter=((pe.month - 1) // 3) + 1,
                        period_end_date=pe,
                        announcement_date=ann,
                        as_known_at=ann,
                        revenue=rev or None,
                        ebitda=ebitda or None,
                        pat=pat or None,
                        total_debt=debt or None,
                        cash=cash or None,
                        net_worth=eq or None,
                        operating_cash_flow=ocf or None,
                        source_id=source_id,
                        parser_version="yfinance-v1",
                    )
                )
                rows_added += 1
        except Exception as e:
            log.warning("yf.quarterly_failed", symbol=sym, error=str(e))
    return rows_added


def cmd_bulk(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("data_fetcher.bulk")

    symbols = _DEFAULT_SYMBOLS[:]
    if args.symbols_file:
        symbols = [
            line.strip()
            for line in Path(args.symbols_file).read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
    log.info("bulk.start", symbols=len(symbols), start=str(args.start), end=str(args.end))

    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with get_session(settings.sqlite_url) as session:
        rows, failed = fetch_prices_yfinance(
            session, symbols=symbols, start=args.start, end=args.end, log=log
        )
        log.info("bulk.prices_done", rows_added=rows, symbols_failed=failed)

        bench_rows = fetch_benchmark_yfinance(
            session, start=args.start, end=args.end, log=log
        )

        # Seed delisted defaults if not already
        delisted_src = register_source(
            session,
            source_type="delisted_defaults",
            source_url=None,
            document_hash=None,
            source_tier=1,
            parser_version="curated-v1",
            notes="curated starter delisted seed list",
        )
        seeded_delisted = seed_delisted_defaults(session, source_id=delisted_src.id, log=log)
        finalize_source(session, delisted_src, rows_added=seeded_delisted)

        # Index constituents (over the active symbols)
        idx_src = register_source(
            session,
            source_type="index_constituents_yf",
            source_url=None,
            document_hash=None,
            source_tier=4,
            parser_version="static-v1",
            notes="static constituents from active symbols list",
        )
        idx_rows = seed_index_constituents(session, symbols=symbols, source_id=idx_src.id)
        finalize_source(session, idx_src, rows_added=idx_rows)

        if not args.skip_financials:
            fin_src = register_source(
                session,
                source_type="yfinance_financials",
                source_url="https://query2.finance.yahoo.com/",
                document_hash=None,
                source_tier=4,
                parser_version="yfinance-v1",
            )
            fin_rows = fetch_quarterly_financials(
                session, symbols=symbols, log=log, source_id=fin_src.id
            )
            finalize_source(session, fin_src, rows_added=fin_rows)
            log.info("bulk.financials_done", rows_added=fin_rows)

    print(f"OK prices={rows} failed={failed} benchmark={bench_rows} index={idx_rows} delisted={seeded_delisted}")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings)
    log = get_logger("data_fetcher.refresh")

    rng = random.Random(args.seed)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with get_session(settings.sqlite_url) as session:
        if args.random_symbols:
            existing_syms = list(
                session.execute(select(Company.symbol).where(Company.exchange == "NSE")).scalars().all()
            )
            pool = [s for s in _DEFAULT_SYMBOLS if s not in existing_syms]
            if pool:
                pick = rng.sample(pool, min(args.random_symbols, len(pool)))
                end = date.today()
                start = end - timedelta(days=365 * args.extend_history_years)
                rows, failed = fetch_prices_yfinance(
                    session, symbols=pick, start=start, end=end, log=log
                )
                log.info("refresh.added_symbols", picked=len(pick), rows=rows, failed=failed)

        if args.extend_history_years:
            existing_syms = list(
                session.execute(select(Company.symbol).where(Company.exchange == "NSE")).scalars().all()
            )
            existing_syms = rng.sample(existing_syms, min(args.refresh_count, len(existing_syms)))
            today = date.today()
            start = today - timedelta(days=365 * args.extend_history_years)
            rows, failed = fetch_prices_yfinance(
                session, symbols=existing_syms, start=start, end=today, log=log
            )
            log.info("refresh.extended", rows=rows, failed=failed)

    print("OK")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    p_bulk = sub.add_parser("bulk", help="initial bulk download")
    p_bulk.add_argument("--start", type=date.fromisoformat, default=date(2014, 1, 1))
    p_bulk.add_argument("--end", type=date.fromisoformat, default=date.today())
    p_bulk.add_argument("--symbols-file", type=str, default=None)
    p_bulk.add_argument("--skip-financials", action="store_true")
    p_bulk.set_defaults(func=cmd_bulk)

    p_ref = sub.add_parser("refresh", help="evolve dataset with new stocks / extended history")
    p_ref.add_argument("--random-symbols", type=int, default=0)
    p_ref.add_argument("--refresh-count", type=int, default=20)
    p_ref.add_argument("--extend-history-years", type=int, default=0)
    p_ref.add_argument("--seed", type=int, default=42)
    p_ref.set_defaults(func=cmd_refresh)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
