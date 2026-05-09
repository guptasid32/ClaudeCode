"""Load benchmark prices (Nifty 500 TRI etc.) from a CSV file.

Expected CSV columns:
    trade_date, close, tri_close

`tri_close` is the Total Return Index close (with dividends reinvested).
If your source only provides PRI, set tri_close = close. The system will
warn — TRI vs PRI matters for honest alpha measurement
(benchmark_methodology.md section 2).

Usage:

    python -m india_monthly_alpha_engine.tools.load_benchmark \
        --index NIFTY_500_TRI --csv data/raw/benchmarks/nifty500_tri.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..app.config import get_settings
from ..db.models import BenchmarkPrice
from ..db.session import get_session
from ..ingestion._helpers import parse_date, parse_float_or_none, read_csv_dicts
from ..ingestion.source_registry import finalize_source, hash_file, register_source


def load_benchmark(session: Session, *, index_name: str, csv_path: Path) -> tuple[int, int]:
    src = register_source(
        session,
        source_type="benchmark_prices_csv",
        source_url=str(csv_path),
        document_hash=hash_file(csv_path),
        source_tier=1,
        parser_version="v0",
    )
    rows_added = 0
    rows_skipped = 0
    for row in read_csv_dicts(csv_path):
        trade_date = parse_date(row["trade_date"])
        close = float(row["close"])
        tri_close = parse_float_or_none(row.get("tri_close"))

        existing = session.execute(
            select(BenchmarkPrice).where(
                BenchmarkPrice.index_name == index_name,
                BenchmarkPrice.trade_date == trade_date,
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                BenchmarkPrice(
                    index_name=index_name,
                    trade_date=trade_date,
                    close=close,
                    tri_close=tri_close if tri_close is not None else close,
                    source_id=src.id,
                )
            )
            rows_added += 1
        else:
            rows_skipped += 1
    finalize_source(session, src, rows_added=rows_added, rows_updated=0)
    return rows_added, rows_skipped


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", type=str, required=True)
    p.add_argument("--csv", type=Path, required=True)
    args = p.parse_args()

    settings = get_settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    with get_session(settings.sqlite_url) as session:
        added, skipped = load_benchmark(session, index_name=args.index, csv_path=args.csv)

    print(f"OK index={args.index} rows_added={added} rows_skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
